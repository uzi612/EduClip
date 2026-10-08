"""Serializers for api_v1 (BACKEND-03)."""
from rest_framework import serializers

from services.youtube import extract_video_id

YOUTUBE_URL_HELP = "Expected youtube.com/watch?v=..., youtu.be/..., or youtube.com/shorts/..."


class ProcessVideoSerializer(serializers.Serializer):
    youtube_url = serializers.CharField(max_length=500)
    options = serializers.DictField(required=False, default=dict)

    def validate_youtube_url(self, value):
        if not extract_video_id(value):
            raise serializers.ValidationError(
                f"Not a valid YouTube URL. {YOUTUBE_URL_HELP}")
        return value.strip()

    @property
    def youtube_id(self):
        return extract_video_id(self.validated_data["youtube_url"])

    def validated_options(self):
        opts = self.validated_data.get("options") or {}
        try:
            flashcard_count = int(opts.get("flashcard_count", 10))
        except (TypeError, ValueError):
            flashcard_count = 10
        return {
            "language": str(opts.get("language", "en"))[:10],
            "flashcard_count": max(5, min(20, flashcard_count)),
            "include_analytics": bool(opts.get("include_analytics", True)),
        }
