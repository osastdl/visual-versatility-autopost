#!/usr/bin/env python3
"""
Read-only analytics pull for Visual Versatility's Instagram + Facebook.

Does NOT post anything. For every already-published entry in
content/calendar.json (and content/posted_log.json), it pulls per-post
insights from the Meta Graph API, then aggregates:

  * top posts by views / reach / interactions
  * average performance grouped by content type (calming video vs branded
    video vs branded static vs ad-shoot vs one-off)
  * average performance grouped by posting hour (SAST) and weekday
  * audience geography (follower / reached / engaged country breakdown)
    with USA / UK / Canada / Australia / Europe rolled up

Writes content/insights_report.json and prints the same JSON to stdout
between markers so it can be scraped from the Actions log.

Env vars (same GitHub secrets as autopost.py):
  IG_ACCESS_TOKEN, IG_USER_ID, FB_PAGE_ID, FB_PAGE_TOKEN
"""

import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

GRAPH = "https://graph.facebook.com/v21.0"
HERE = os.path.dirname(__file__)
CALENDAR_PATH = os.path.join(HERE, "..", "content", "calendar.json")
POSTED_LOG_PATH = os.path.join(HERE, "..", "content", "posted_log.json")
REPORT_PATH = os.path.join(HERE, "..", "content", "insights_report.json")

IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
IG_USER_ID = os.environ.get("IG_USER_ID")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")

SAST = timezone(timedelta(hours=2))

# Meta keeps trimming which per-media metrics are allowed; request the wide
# set, then fall back to one-at-a-time on error and keep whatever sticks.
IG_MEDIA_METRICS = [
    "views", "reach", "total_interactions", "likes", "comments",
    "saved", "shares", "profile_visits", "follows",
]

EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "IS", "NO", "CH", "LI",
}
TARGET_BUCKETS = {
    "USA": {"US"},
    "UK": {"GB"},
    "Canada": {"CA"},
    "Australia": {"AU"},
    "Europe (ex-UK)": EU_COUNTRIES,
}


def get(url, params, label):
    try:
        r = requests.get(url, params=params, timeout=60)
        j = r.json()
    except Exception as e:  # noqa: BLE001
        return {"__error__": f"{label}: {e}"}
    if isinstance(j, dict) and j.get("error"):
        return {"__error__": f"{label}: {j['error'].get('message')}"}
    return j


def classify(entry_id, source):
    i = (entry_id or "").lower()
    if i.startswith("vv-calm"):
        return "calming video (nature + text overlay)"
    if i.startswith("content-video") or i.startswith("brand-ad"):
        return "branded video"
    if i.startswith("adshoot") or i.startswith("vv-adshoot"):
        return "ad-shoot branded photo"
    if i.startswith("day"):
        return "branded static/carousel"
    if i.startswith("business-card"):
        return "one-off announcement"
    if source == "quickpost":
        return "quickpost photo"
    if source == "manual_video":
        return "manual brand video"
    return "other"


def collect_published():
    published = []
    with open(CALENDAR_PATH) as f:
        for e in json.load(f):
            if e.get("posted") and (e.get("instagram_id") or e.get("facebook_id")):
                published.append({
                    "id": e.get("id"),
                    "kind": classify(e.get("id"), None),
                    "instagram_id": e.get("instagram_id"),
                    "facebook_id": e.get("facebook_id"),
                    "posted_at": e.get("posted_at") or e.get("scheduled_at"),
                    "caption": (e.get("caption") or "").split("\n")[0][:90],
                })
    if os.path.exists(POSTED_LOG_PATH):
        with open(POSTED_LOG_PATH) as f:
            for e in json.load(f):
                if e.get("instagram_id") or e.get("facebook_id"):
                    published.append({
                        "id": e.get("thumbnail_url", "").rsplit("/", 1)[-1] or "posted_log",
                        "kind": classify(None, e.get("source")),
                        "instagram_id": e.get("instagram_id"),
                        "facebook_id": e.get("facebook_id"),
                        "posted_at": e.get("posted_at"),
                        "caption": (e.get("caption") or "").split("\n")[0][:90],
                    })
    return published


def ig_media_detail(media_id):
    j = get(f"{GRAPH}/{media_id}",
            {"fields": "id,media_type,media_product_type,timestamp,permalink,like_count,comments_count",
             "access_token": IG_ACCESS_TOKEN}, "ig_media_detail")
    return j


def ig_media_insights(media_id):
    def parse(j):
        out = {}
        for row in j.get("data", []):
            name = row.get("name")
            vals = row.get("values") or [{}]
            out[name] = vals[0].get("value")
        return out

    j = get(f"{GRAPH}/{media_id}/insights",
            {"metric": ",".join(IG_MEDIA_METRICS), "access_token": IG_ACCESS_TOKEN},
            "ig_insights")
    if "__error__" not in j:
        return parse(j), None
    # fall back: one metric at a time
    merged, errs = {}, []
    for m in IG_MEDIA_METRICS:
        jm = get(f"{GRAPH}/{media_id}/insights",
                 {"metric": m, "access_token": IG_ACCESS_TOKEN}, f"ig_insights[{m}]")
        if "__error__" in jm:
            errs.append(m)
            continue
        merged.update(parse(jm))
    return merged, (f"unavailable: {','.join(errs)}" if errs else None)


def ig_audience():
    """follower_demographics + reached/engaged audience, country breakdown."""
    out = {}
    combos = [
        ("followers", "follower_demographics", [{"period": "lifetime"}]),
        ("reached", "reached_audience_demographics",
         [{"period": "lifetime", "timeframe": tf} for tf in ("this_week", "this_month", "prev_month")]),
        ("engaged", "engaged_audience_demographics",
         [{"period": "lifetime", "timeframe": tf} for tf in ("this_week", "this_month", "prev_month")]),
    ]
    for key, metric, attempts in combos:
        j = None
        for extra in attempts:
            params = {"metric": metric, "metric_type": "total_value",
                      "breakdown": "country", "access_token": IG_ACCESS_TOKEN}
            params.update(extra)
            j = get(f"{GRAPH}/{IG_USER_ID}/insights", params, f"ig_audience[{key}:{extra.get('timeframe','-')}]")
            if "__error__" not in j:
                out.setdefault("_meta", {})[key] = extra
                break
        if j is None or "__error__" in j:
            out[key] = {"error": j["__error__"] if j else "no attempt"}
            continue
        try:
            results = j["data"][0]["total_value"]["breakdowns"][0]["results"]
            by_country = {r["dimension_values"][0]: r["value"] for r in results}
            out[key] = summarize_geo(by_country)
        except Exception as e:  # noqa: BLE001
            out[key] = {"error": f"parse: {e}", "raw": j.get("data")}
    return out


def summarize_geo(by_country):
    total = sum(by_country.values()) or 1
    buckets = {}
    for name, codes in TARGET_BUCKETS.items():
        v = sum(by_country.get(c, 0) for c in codes)
        buckets[name] = {"count": v, "pct": round(100 * v / total, 1)}
    target_total = sum(b["count"] for b in buckets.values())
    top = sorted(by_country.items(), key=lambda kv: kv[1], reverse=True)[:12]
    return {
        "total_measured": total,
        "target_markets": buckets,
        "target_markets_combined_pct": round(100 * target_total / total, 1),
        "top_countries": [{"country": c, "count": v, "pct": round(100 * v / total, 1)} for c, v in top],
    }


def fb_post_insights(fb_id):
    detail = get(f"{GRAPH}/{fb_id}",
                 {"fields": "id,created_time,permalink_url", "access_token": FB_PAGE_TOKEN},
                 "fb_detail")
    ins = get(f"{GRAPH}/{fb_id}/insights",
              {"metric": "post_impressions,post_impressions_unique,post_engaged_users,post_clicks",
               "access_token": FB_PAGE_TOKEN}, "fb_insights")
    out = {}
    if "__error__" not in ins:
        for row in ins.get("data", []):
            vals = row.get("values") or [{}]
            out[row["name"]] = vals[0].get("value")
    else:
        out["error"] = ins["__error__"]
    if "__error__" not in detail:
        out["permalink"] = detail.get("permalink_url")
    return out


def fb_page_audience():
    attempts = [
        ({"metric": "page_fans_country", "period": "lifetime"}, "page_fans_country"),
        ({"metric": "page_impressions_by_country_unique", "period": "days_28"}, "page_impr_country"),
    ]
    for params, label in attempts:
        params["access_token"] = FB_PAGE_TOKEN
        j = get(f"{GRAPH}/{FB_PAGE_ID}/insights", params, label)
        if "__error__" in j:
            last = j["__error__"]
            continue
        try:
            vals = j["data"][0]["values"][-1]["value"]
            if vals:
                res = summarize_geo(vals)
                res["_source_metric"] = label
                return res
        except Exception as e:  # noqa: BLE001
            last = f"parse: {e}"
    return {"error": last, "note": "Meta removed most Page country demographics in v20+"}


def main():
    published = collect_published()
    print(f"Found {len(published)} published entries with a platform id.\n")

    posts = []
    for p in published:
        rec = dict(p)
        if p["instagram_id"]:
            d = ig_media_detail(p["instagram_id"])
            ins, note = ig_media_insights(p["instagram_id"])
            ts = d.get("timestamp") if "__error__" not in d else None
            rec["ig"] = {
                "media_type": d.get("media_type") if "__error__" not in d else None,
                "product_type": d.get("media_product_type") if "__error__" not in d else None,
                "timestamp": ts,
                "permalink": d.get("permalink") if "__error__" not in d else None,
                "like_count": d.get("like_count") if "__error__" not in d else None,
                "comments_count": d.get("comments_count") if "__error__" not in d else None,
                "insights": ins,
                "note": note,
            }
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("+0000", "+00:00")).astimezone(SAST)
                    rec["sast_hour"] = dt.hour
                    rec["weekday"] = dt.strftime("%a")
                    rec["sast_time"] = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:  # noqa: BLE001
                    pass
        if p["facebook_id"]:
            rec["fb"] = fb_post_insights(p["facebook_id"])
        posts.append(rec)

    def v(rec, k):
        return (rec.get("ig", {}).get("insights", {}) or {}).get(k) or 0

    ranked_views = sorted(posts, key=lambda r: v(r, "views"), reverse=True)
    ranked_reach = sorted(posts, key=lambda r: v(r, "reach"), reverse=True)
    ranked_inter = sorted(posts, key=lambda r: v(r, "total_interactions"), reverse=True)

    def slim(r):
        return {
            "id": r["id"], "kind": r["kind"], "sast_time": r.get("sast_time"),
            "weekday": r.get("weekday"), "caption": r["caption"],
            "views": v(r, "views"), "reach": v(r, "reach"),
            "interactions": v(r, "total_interactions"),
            "likes": v(r, "likes") or r.get("ig", {}).get("like_count"),
            "comments": v(r, "comments") or r.get("ig", {}).get("comments_count"),
            "saved": v(r, "saved"), "shares": v(r, "shares"),
            "permalink": r.get("ig", {}).get("permalink"),
        }

    by_kind = defaultdict(list)
    for r in posts:
        by_kind[r["kind"]].append(r)
    kind_summary = {}
    for kind, rs in by_kind.items():
        views = [v(r, "views") for r in rs if v(r, "views")]
        reach = [v(r, "reach") for r in rs if v(r, "reach")]
        inter = [v(r, "total_interactions") for r in rs if v(r, "total_interactions")]
        kind_summary[kind] = {
            "posts": len(rs),
            "avg_views": round(statistics.mean(views), 1) if views else None,
            "median_views": round(statistics.median(views), 1) if views else None,
            "max_views": max(views) if views else None,
            "avg_reach": round(statistics.mean(reach), 1) if reach else None,
            "avg_interactions": round(statistics.mean(inter), 1) if inter else None,
        }

    by_hour = defaultdict(list)
    by_wday = defaultdict(list)
    for r in posts:
        if "sast_hour" in r and v(r, "views"):
            by_hour[r["sast_hour"]].append(v(r, "views"))
        if "weekday" in r and v(r, "views"):
            by_wday[r["weekday"]].append(v(r, "views"))
    hour_summary = {
        str(h): {"posts": len(vs), "avg_views": round(statistics.mean(vs), 1)}
        for h, vs in sorted(by_hour.items())
    }
    wday_summary = {
        w: {"posts": len(vs), "avg_views": round(statistics.mean(vs), 1)}
        for w, vs in by_wday.items()
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "published_count": len(posts),
        "top_by_views": [slim(r) for r in ranked_views[:12]],
        "top_by_reach": [slim(r) for r in ranked_reach[:12]],
        "top_by_interactions": [slim(r) for r in ranked_inter[:12]],
        "by_content_type": kind_summary,
        "by_posting_hour_sast": hour_summary,
        "by_weekday": wday_summary,
        "audience_geography_instagram": ig_audience(),
        "audience_geography_facebook": fb_page_audience(),
        "all_posts": [slim(r) for r in ranked_views],
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print("=== INSIGHTS_JSON_START ===")
    print(json.dumps(report, indent=2))
    print("=== INSIGHTS_JSON_END ===")


if __name__ == "__main__":
    missing = [n for n, val in [
        ("IG_ACCESS_TOKEN", IG_ACCESS_TOKEN), ("IG_USER_ID", IG_USER_ID),
        ("FB_PAGE_ID", FB_PAGE_ID), ("FB_PAGE_TOKEN", FB_PAGE_TOKEN),
    ] if not val]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    main()
