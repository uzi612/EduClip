"""Throttles for api_v1 (BACKEND-03). Rate set in settings REST_FRAMEWORK."""
from rest_framework.throttling import AnonRateThrottle


class ProcessVideoThrottle(AnonRateThrottle):
    scope = "process_video"
