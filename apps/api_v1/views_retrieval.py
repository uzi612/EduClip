"""Retrieval endpoints (BACKEND-04): video detail, chapters, flashcards,
analytics, list, delete. See docs/API_SPECIFICATION.md §4-10."""
from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.api_v1.exceptions import request_id_of
from apps.api_v1.presenters import (
    chapter_dict,
    detail_video,
    flashcard_dict,
    list_item,
    progress_video,
    video_lookup_or_none,
)

CACHE_60 = {"Cache-Control": "public, max-age=60"}


def _not_found(request=None):
    return Response({"error": {"code": "VIDEO_NOT_FOUND",
                                "message": "No video with that id.",
                                "details": {}, "request_id": request_id_of(request),
                                "retryable": False}}, status=404)


def _db_guarded(request=None):
    """Ensure MongoEngine is connected; returns an error Response or None."""
    from apps.videos.db import ensure_mongoengine

    try:
        ensure_mongoengine()
    except RuntimeError as exc:
        return Response({"error": {"code": "SERVICE_UNAVAILABLE", "message": str(exc),
                                    "details": {}, "request_id": request_id_of(request),
                                    "retryable": True}}, status=503)
    return None


def _cached_response(data, status=200):
    response = Response(data, status=status)
    response["Cache-Control"] = "public, max-age=60"
    return response


@api_view(["GET", "DELETE"])
def video_detail(request, video_id):
    """GET full payload (polling contract) / DELETE with cascade."""
    guard = _db_guarded(request)
    if guard is not None:
        return guard
    video = video_lookup_or_none(video_id)
    if video is None:
        return _not_found(request)
    if request.method == "DELETE":
        from apps.videos.video_service import delete_video_records

        delete_video_records(video)
        return HttpResponse(status=204)
    if video.status == "failed":
        return Response({
            "video_id": str(video.id), "status": "failed", "progress": 0.0,
            "error": {"code": "PROCESSING_FAILED",
                      "message": video.error or "Video processing failed.",
                      "details": {}, "request_id": request_id_of(request),
                      "retryable": True},
        }, status=422)
    if video.status != "ready":
        return _cached_response(progress_video(video))
    from apps.analytics.models import Analytics

    analytics = Analytics.objects(video_id=video).first()
    return _cached_response(detail_video(video, analytics))


@api_view(["GET"])
def video_chapters(request, video_id):
    guard = _db_guarded(request)
    if guard is not None:
        return guard
    video = video_lookup_or_none(video_id)
    if video is None:
        return _not_found(request)
    return _cached_response({
        "video_id": str(video.id),
        "duration_sec": video.duration_sec,
        "chapters": [chapter_dict(c) for c in (video.chapters or [])],
    })


@api_view(["GET"])
def video_flashcards(request, video_id):
    guard = _db_guarded(request)
    if guard is not None:
        return guard
    video = video_lookup_or_none(video_id)
    if video is None:
        return _not_found(request)
    from apps.flashcards.models import Flashcard

    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 10))))
    except (TypeError, ValueError):
        return Response({"error": {"code": "VALIDATION_ERROR",
                                    "message": "page and page_size must be integers.",
                                    "details": {}, "request_id": request_id_of(request),
                                    "retryable": False}}, status=400)
    qs = Flashcard.objects(video_id=video).order_by("timestamp_sec", "id")
    total = qs.count()
    cards = qs.skip((page - 1) * page_size).limit(page_size)
    return _cached_response({
        "video_id": str(video.id),
        "page": page,
        "page_size": page_size,
        "total": total,
        "flashcards": [flashcard_dict(c) for c in cards],
    })


@api_view(["GET"])
def video_analytics(request, video_id):
    guard = _db_guarded(request)
    if guard is not None:
        return guard
    video = video_lookup_or_none(video_id)
    if video is None:
        return _not_found(request)
    from apps.analytics.models import Analytics

    analytics = Analytics.objects(video_id=video).first()
    if analytics is None:
        return Response({"error": {"code": "ANALYTICS_PENDING",
                                    "message": "Analytics are not computed yet. Poll again.",
                                    "details": {}, "request_id": request_id_of(request),
                                    "retryable": True}}, status=404)
    return _cached_response({
        "video_id": str(video.id),
        "graphs": dict(analytics.graphs or {}),
        "stats": dict(analytics.stats or {}),
    })


@api_view(["GET"])
def videos_list(request):
    """Paginated recent videos. ?status= (default ready, use all for everything),
    ?search= title substring, ?page=&page_size=."""
    guard = _db_guarded(request)
    if guard is not None:
        return guard
    from apps.videos.models import Video

    status = request.query_params.get("status", "ready")
    search = (request.query_params.get("search", "") or "").strip()
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 12))))
    except (TypeError, ValueError):
        return Response({"error": {"code": "VALIDATION_ERROR",
                                    "message": "page and page_size must be integers.",
                                    "details": {}, "request_id": request_id_of(request),
                                    "retryable": False}}, status=400)
    qs = Video.objects()
    if status and status != "all":
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(title__icontains=search)
    qs = qs.order_by("-created_at")
    total = qs.count()
    items = qs.skip((page - 1) * page_size).limit(page_size)
    return _cached_response({
        "page": page, "page_size": page_size, "total": total,
        "items": [list_item(v) for v in items],
    })

