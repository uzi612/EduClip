"""BACKEND-05 verification: models + DAO helpers against in-memory mongomock.

Run: python -m pytest apps/videos/tests/test_models_dao.py -q
(or: python apps/videos/tests/test_models_dao.py)
"""
import mongomock
import mongoengine as me
from mongoengine.errors import NotUniqueError, ValidationError

from apps.analytics.models import Analytics
from apps.flashcards.models import Flashcard
from apps.videos.models import SCHEMA_VERSION, Video
from services import mongo as mongo_svc

VID = "dQw4w9WgXcQ"


def setup_module():
    me.disconnect_all()
    me.connect("educlip-test", mongo_client_class=mongomock.MongoClient)


def teardown_module():
    me.disconnect_all()


def _video(**kw):
    args = {"youtube_id": VID, "title": "T", "duration_sec": 100}
    args.update(kw)
    return Video(**args)


def test_video_defaults():
    v = _video().save()
    assert v.status == "queued" and v.progress == 0.0 and v.schema_version == SCHEMA_VERSION
    v.delete()


def test_video_rejects_bad_youtube_id():
    try:
        _video(youtube_id="short").save()
    except ValidationError:
        return
    raise AssertionError("expected ValidationError for bad youtube_id")


def test_video_rejects_bad_duration_and_status():
    for kw in ({"duration_sec": 5}, {"duration_sec": 99999}, {"status": "nope"}):
        try:
            _video(**kw).save()
        except ValidationError:
            continue
        raise AssertionError(f"expected ValidationError for {kw}")


def test_video_unique_youtube_id_and_meta():
    idx = Video._meta["index_specs"]
    assert any(i.get("unique") and "youtube_id" in str(i.get("fields")) for i in idx)
    _video().save()
    try:
        _video(title="dup").save()
    except NotUniqueError:
        return
    finally:
        Video.objects(youtube_id=VID).delete()
    raise AssertionError("expected NotUniqueError for duplicate youtube_id")


def test_flashcard_limits():
    v = _video().save()
    try:
        Flashcard(video_id=v, front="Q", back="A", timestamp_sec=0).save()
        try:
            Flashcard(video_id=v, front="x" * 141, back="A", timestamp_sec=0).save()
        except ValidationError:
            return
        raise AssertionError("expected ValidationError for front > 140 chars")
    finally:
        Flashcard.objects(video_id=v).delete()
        v.delete()


def test_analytics_requires_stats_graphs():
    v = _video().save()
    try:
        Analytics(video_id=v, stats={"word_count": 1}, graphs={"a": 1}).save()
        try:
            Analytics(video_id=v, stats={}, graphs={}).save()
        except (ValidationError, NotUniqueError):
            return
        raise AssertionError("expected duplicate/validation error for second analytics")
    finally:
        Analytics.objects(video_id=v).delete()
        v.delete()


def test_dao_helpers_with_mongomock():
    db = mongomock.MongoClient().educlip
    vid = db.videos.insert_one(
        {"youtube_id": VID, "status": "processing", "progress": 0.2, "created_at": 1}
    ).inserted_id
    assert mongo_svc.mark_ready(db, vid, {"summary": "s"}) is True
    assert mongo_svc.mark_ready(db, vid, {}) is False  # already ready
    assert db.videos.find_one({"_id": vid})["status"] == "ready"

    mongo_svc.insert_flashcards_bulk(db, [])
    mongo_svc.insert_flashcards_bulk(
        db, [{"video_id": vid, "front": "Q1", "timestamp_sec": 5}]
    )
    assert db.flashcards.count_documents({}) == 1

    got = mongo_svc.recent_videos(db, page=1, page_size=10)
    assert len(got) == 1 and "full_text" not in got[0]

    assert mongo_svc.get_transcript({"transcript_segments": [{"start": 0}]}) == [{"start": 0}]
    db.transcripts_overflow.insert_one({"video_id": vid, "bucket": 0, "segments": [{"start": 1}]})
    assert mongo_svc.get_transcript({"_id": vid}, db=db) == [{"start": 1}]


if __name__ == "__main__":
    setup_module()
    for name, fn in sorted(
        [(k, v) for k, v in globals().items() if k.startswith("test_")]
    ):
        fn()
        print(f"PASS {name}")
    teardown_module()
    print("ALL BACKEND-05 CHECKS PASSED")
