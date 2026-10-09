"""Local-review end-to-end probe (dev settings, real network, no keys).

Usage: $env:PYTHONPATH='.'; $env:DJANGO_SETTINGS_MODULE='config.settings.dev'
       python scripts/e2e_local_review.py '<youtube_url>'
Writes scripts/e2e_result.json (UTF-8) and prints an ASCII-safe summary.
"""
import io
import json
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from django.test import Client  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "https://youtu.be/IecCQPX-QsI"

client = Client()
post = client.post("/api/v1/process-video", {"youtube_url": URL},
                   content_type="application/json", HTTP_HOST="localhost")
result = {"post_status": post.status_code, "post": post.json()}
vid = result["post"].get("video_id")
if vid:
    result["endpoints"] = {}
    for name, path in [("detail", f"/api/v1/video/{vid}/"),
                       ("chapters", f"/api/v1/video/{vid}/chapters"),
                       ("flashcards", f"/api/v1/video/{vid}/flashcards"),
                       ("analytics", f"/api/v1/video/{vid}/analytics"),
                       ("list", "/api/v1/videos/")]:
        r = client.get(path, HTTP_HOST="localhost")
        try:
            body = r.json()
        except Exception:
            body = {"_non_json": True}
        result["endpoints"][name] = {"status": r.status_code, "body": body}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e_result.json")
with io.open(out, "w", encoding="utf-8") as fh:
    json.dump(result, fh, ensure_ascii=False, indent=1)

detail = result["endpoints"]["detail"]["body"]
print("POST:", result["post_status"], "| DETAIL:", result["endpoints"]["detail"]["status"])
print("STATUS:", detail.get("status"), "| DEGRADED:", detail.get("degraded"))
print("TITLE:", detail.get("title", "")[:80])
print("FULLTEXT_LEN:", len(detail.get("summary", "")))
print("N CHAPTERS:", len(detail.get("chapters", [])))
print("N KEYWORDS:", len(detail.get("keywords", [])))
print("FLASHCARD_COUNT:", detail.get("flashcard_count"))
print("ANALYTICS:", result["endpoints"]["analytics"]["status"],
      list(result["endpoints"]["analytics"]["body"].get("graphs", {}).keys()))
print("WROTE:", out)
