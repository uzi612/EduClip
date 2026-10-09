"""End-to-end regression matrix (DEPLOY-01).

URL input -> POST -> worker pipeline -> detail/chapters/flashcards/analytics,
plus seek-sync preconditions, CORS, and cache headers. Fully offline: dev
settings (mongomock + eager tasks), mocked transcript/metadata/LLM boundaries.
Optional live probe with real network: EDUCLIP_E2E_LIVE=1 EDUCLIP_E2E_URL=<url>.

Run: python tests/test_e2e_pipeline.py (needs repo root on PYTHONPATH)
Writes: tests/e2e_report.json (gitignored) + PASS matrix to stdout.
"""
import io
import json
import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from django.conf import settings  # noqa: E402

if "testserver" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]

from unittest.mock import MagicMock, patch  # noqa: E402

import mongomock  # noqa: E402
import mongoengine as me  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.analytics.models import Analytics  # noqa: E402
from apps.analytics.validators import ChartValidator  # noqa: E402
from apps.flashcards.models import Flashcard  # noqa: E402
from apps.videos.models import Video  # noqa: E402
from apps.videos.tasks import process_video_task  # noqa: E402
from apps.videos.video_service import get_or_create_video  # noqa: E402

REPORT = {"scenarios": [], "manual": "see tests/e2e_matrix.md"}
META = {"title": "T", "channel": "C",
        "thumbnail": "https://i.ytimg.com/vi/x/hqdefault.jpg", "duration_sec": 600}


def _client():
    return APIClient(HTTP_HOST="testserver")


def _clean():
    for doc in (Flashcard, Analytics, Video):
        doc.objects.delete()


def _record(name, ok, ms, detail=""):
    REPORT["scenarios"].append({"name": name, "ok": bool(ok),
                                "ms": round(ms, 1), "detail": detail})
    status = "PASS" if ok else "FAIL"
    print(f"{status} {name} ({ms:.0f}ms) {detail}")


def _segments(n, span_sec, vocab=("alpha", "beta", "gamma")):
    step = span_sec / max(n, 1)
    return [{"start": i * step, "duration": step,
             "text": f"{vocab[i % len(vocab)]} lesson segment number {i}."}
            for i in range(n)]


def _analysis(duration, titles, keywords, n_cards=3):
    from apps.analytics.graphs import build_all_graphs

    segs = _segments(10, duration)
    span = duration // max(len(titles), 1)
    chapters = [{"index": i, "title": t, "start_sec": i * span,
                 "end_sec": min(duration, (i + 1) * span) if i < len(titles) - 1 else duration,
                 "summary": "", "keyword_refs": []}
                for i, t in enumerate(titles)]
    kw = [{"term": k["term"], "score": k["score"], "count": k["count"]} for k in keywords]
    cards = [{"front": f"Q{i}?", "back": f"A{i}.", "timestamp_sec": i * 10}
             for i in range(n_cards)]
    return {
        "summary": "Extractive-style summary of the lesson.",
        "chapters": chapters, "keywords": kw, "flashcards": cards,
        "stats": {"word_count": 100, "reading_minutes": 1, "avg_words_per_min": 100,
                  "top_keywords": [k["term"] for k in kw[:3]]},
        "complexity": {"type_token_ratio": 0.5, "avg_words_per_sentence": 8.0,
                       "long_word_ratio": 0.2},
        "graphs": build_all_graphs(segs, kw, chapters, duration),
        "degraded": False,
    }


def _full_flow(name, youtube_id, duration, chapters, keywords, source="youtube_captions"):
    """POST -> eager task skipped (run inline) -> all GETs -> contract asserts."""
    _clean()
    started = time.perf_counter()
    meta = dict(META, duration_sec=duration)
    segs = _segments(10, duration)
    full = " ".join(s["text"] for s in segs)
    analysis = _analysis(duration, chapters, keywords)
    with patch("services.youtube.get_video_metadata", return_value=meta), patch(
        "apps.videos.tasks.process_video_task") as task:
        task.delay.return_value = MagicMock(id="task-e2e")
        post = _client().post("/api/v1/process-video",
                              {"youtube_url": f"https://youtu.be/{youtube_id}"},
                              format="json")
        assert post.status_code == 202, post.content
        vid = post.json()["video_id"]
    video, _ = get_or_create_video(youtube_id, meta)
    assert str(video.id) == vid
    with patch("apps.videos.transcribe.transcribe_video",
               return_value=(segs, full, source)), patch(
        "apps.analytics.pipeline.run_analysis", return_value=analysis):
        out = process_video_task.run(vid)
    assert out["status"] == "ready", out
    client = _client()
    detail = client.get(f"/api/v1/video/{vid}/", HTTP_HOST="testserver").json()
    assert detail["status"] == "ready" and detail["flashcard_count"] == len(analysis["flashcards"])
    for ch in detail["chapters"]:
        assert 0 <= ch["start_sec"] < ch["end_sec"] <= duration, ch  # seek-sync precondition
    cards = client.get(f"/api/v1/video/{vid}/flashcards", HTTP_HOST="testserver").json()
    assert cards["total"] == len(analysis["flashcards"])
    for card in cards["flashcards"]:
        assert 0 <= card["timestamp_sec"] <= duration, card  # seek-sync precondition
    graphs = client.get(f"/api/v1/video/{vid}/analytics", HTTP_HOST="testserver").json()
    assert ChartValidator.validate(graphs["graphs"]) is True
    ms = (time.perf_counter() - started) * 1000
    return vid, ms, detail


def setup_module():
    me.disconnect_all()
    me.connect("educlip-test", mongo_client_class=mongomock.MongoClient)


def teardown_module():
    me.disconnect_all()


def test_scenario_standard_lecture():
    vid, ms, detail = _full_flow(
        "standard", "dQw4w9WgXcQ", 600, ["Intro", "Deep dive", "Recap"],
        [{"term": "alpha", "score": 0.9, "count": 4}])
    _record("standard-lecture", True, ms, f"chapters={len(detail['chapters'])}")


def test_scenario_shorts_60s():
    vid, ms, detail = _full_flow(
        "shorts", "9bZkp7q19f0", 60, ["Quick tip"],
        [{"term": "beta", "score": 0.8, "count": 3}])
    _record("shorts-60s", True, ms, "single short chapter")


def test_scenario_long_2h_buckets():
    vid, ms, detail = _full_flow(
        "long", "jNQXAC9IVRw", 7200, ["Part 1", "Part 2"],
        [{"term": "gamma", "score": 0.85, "count": 6}])
    from django.test import Client as DjClient

    graphs = DjClient().get(
        f"/api/v1/video/{vid}/analytics", HTTP_HOST="testserver").json()["graphs"]
    n = len(graphs["keyword_density"]["data"]["labels"])
    assert n == 120, n  # 7200s / 60s buckets
    _record("long-2h-buckets", True, ms, f"buckets={n}")


def test_scenario_whisper_fallback_source():
    vid, ms, detail = _full_flow(
        "fallback", "M7lc1UVfVEQ", 600, ["Audio part"],
        [{"term": "alpha", "score": 0.7, "count": 2}], source="whisper_fallback")
    assert detail["transcript_source"] == "whisper_fallback"
    assert detail["degraded"] in (True, False)
    _record("whisper-fallback", True, ms, "source recorded")


def test_scenario_hindi_unicode_real_metrics():
    """No LLM/key mocks on metrics: real normalize + degraded pipeline."""
    _clean()
    started = time.perf_counter()
    from apps.analytics import pipeline as pipeline_mod

    segs = [{"start": float(i * 5), "duration": 5.0,
             "text": f"पोर्टफोलियो डेटा विश्लेषण भाग {i}।"}
            for i in range(40)]
    with patch.object(pipeline_mod.llm_client, "analyze_video",
                      side_effect=Exception("quota exhausted")):
        out = pipeline_mod.run_analysis(segs, "T", 200)
    assert out["degraded"] is True and len(out["keywords"]) >= 3
    assert 0 < len(out["summary"]) <= pipeline_mod.MAX_SUMMARY_CHARS
    assert ChartValidator.validate(out["graphs"]) is True
    _record("hindi-unicode", True, (time.perf_counter() - started) * 1000,
            f"keywords={len(out['keywords'])}")


def test_scenario_empty_transcript_fails_cleanly():
    _clean()
    started = time.perf_counter()
    from services.youtube import TranscriptUnavailableError

    meta = dict(META)
    video, _ = get_or_create_video("dQw4w9WgXcQ", meta)
    with patch("apps.videos.transcribe.transcribe_video",
               side_effect=TranscriptUnavailableError("none", retryable=False)):
        try:
            process_video_task.run(str(video.id))
        except Exception:
            pass
    video.reload()
    assert video.status == "failed" and video.error
    r = _client().get(f"/api/v1/video/{video.id}/", HTTP_HOST="testserver")
    assert r.status_code == 422 and r.json()["error"]["code"] == "PROCESSING_FAILED"
    _record("empty-transcript-fails", True, (time.perf_counter() - started) * 1000,
            "failed + 422 contract")


def test_scenario_invalid_url_and_cors():
    _clean()
    started = time.perf_counter()
    r = _client().post("/api/v1/process-video", {"youtube_url": "https://example.com/x"},
                       format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_URL"
    preflight = _client().options(
        "/api/v1/process-video", HTTP_ORIGIN="https://example.com",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
    assert preflight["Access-Control-Allow-Origin"] == "*", dict(preflight.headers)
    detail = _client().get("/api/v1/videos/", HTTP_HOST="testserver")
    assert detail["Cache-Control"] == "public, max-age=60"
    _record("invalid-url-cors-cache", True, (time.perf_counter() - started) * 1000,
            "400 + ACAO * + cache header")


def test_scenario_live_probe_optional():
    if os.getenv("EDUCLIP_E2E_LIVE") != "1":
        _record("live-probe", True, 0, "skipped (set EDUCLIP_E2E_LIVE=1)")
        return
    started = time.perf_counter()
    url = os.getenv("EDUCLIP_E2E_URL", "https://youtu.be/IecCQPX-QsI")
    r = _client().post("/api/v1/process-video", {"youtube_url": url}, format="json")
    assert r.status_code in (200, 202), r.content
    # NOTE: live task runs inline only under eager dev settings; otherwise poll.
    _record("live-probe", True, (time.perf_counter() - started) * 1000, url)


def _write_report():
    ok = [s for s in REPORT["scenarios"] if s["ok"]]
    timed = [s["ms"] for s in REPORT["scenarios"] if s["ms"] > 0]
    timed.sort()
    REPORT["summary"] = {
        "passed": len(ok), "total": len(REPORT["scenarios"]),
        "median_ms": timed[len(timed) // 2] if timed else 0,
    }
    with io.open("tests/e2e_report.json", "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, indent=1)
    print(f"MATRIX {len(ok)}/{len(REPORT['scenarios'])} passed, "
          f"median {REPORT['summary']['median_ms']:.0f}ms")


if __name__ == "__main__":
    setup_module()
    try:
        for name, fn in sorted([(k, v) for k, v in globals().items()
                                if k.startswith("test_scenario_")]):
            try:
                fn()
            except Exception as exc:  # record-and-continue: matrix over unit-style abort
                _record(name.replace("test_scenario_", ""), False, 0, f"{type(exc).__name__}: {exc}"[:200])
        _write_report()
    finally:
        teardown_module()
    failed = [s for s in REPORT["scenarios"] if not s["ok"]]
    if failed:
        raise SystemExit(f"E2E MATRIX FAILED: {[s['name'] for s in failed]}")
    print("ALL DEPLOY-01 CHECKS PASSED")
