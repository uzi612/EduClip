"""Unified LLM client (BACKEND-02): transcript -> structured insights.

Provider-agnostic: OpenAI `gpt-4o-mini` (JSON mode) primary, Gemini adapter
behind the LLM_PROVIDER setting. All SDK imports are lazy so
`manage.py check` works without optional AI dependencies.

See docs/ARCHITECTURE.md §6.
"""
import hashlib
import json
import logging
import random
import time

logger = logging.getLogger(__name__)

OPENAI_MODEL = "gpt-4o-mini"
OPENAI_TIMEOUT_SEC = 60
GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_TIMEOUT_SEC = 60
MAX_TRANSCRIPT_SEGMENTS = 800
MAX_RETRIES = 2
# Exponential backoff for LLM timeouts/quota (BACKEND-06): delay before the
# retry following attempt N is BACKOFF_BASE_SEC * 2**N plus up to 1s jitter
# so concurrent workers do not thundering-herd the provider.
BACKOFF_BASE_SEC = 1.0
BACKOFF_JITTER_SEC = 1.0


def _backoff_delay(attempt):
    return BACKOFF_BASE_SEC * (2 ** attempt) + random.uniform(0, BACKOFF_JITTER_SEC)

SYSTEM_PROMPT = """You are EduClip, an education analyst. Given a video transcript with
timestamps, return STRICT JSON with exactly these keys:
{"summary": str, "chapters": [...], "keywords": [...], "flashcards": [...]}.
- summary: 3-5 sentences capturing the core lesson.
- chapters: [{"title": str (<=80 chars), "start_sec": int, "end_sec": int,
  "summary": str (<=500 chars)}], covering the whole video, each >=30 seconds.
- keywords: [{"term": str, "score": float 0-1}] (5-10 key domain terms).
- flashcards: 8-12 items [{"front": str (question, <=140 chars),
  "back": str (answer, <=300 chars), "timestamp_sec": int}].
Return JSON only, no markdown fences."""

_cache: dict = {}


class LLMError(Exception):
    """Raised when the LLM call fails or returns an unusable payload."""

    def __init__(self, message, *, retryable=True, provider=None):
        super().__init__(message)
        self.retryable = retryable
        self.provider = provider


def transcript_text(segments, limit=MAX_TRANSCRIPT_SEGMENTS):
    """Render segments as timestamped lines, truncated to `limit` entries."""
    lines = []
    for seg in (segments or [])[:limit]:
        lines.append(f"[{float(seg.get('start', 0)):.0f}s] {seg.get('text', '')}")
    return "\n".join(lines)


def cache_key(full_text):
    """Stable cache key so identical re-uploads cost $0 (see ARCHITECTURE §6)."""
    return hashlib.sha256((full_text or "").encode("utf-8")).hexdigest()


def _provider_name(explicit=None):
    if explicit:
        return explicit
    try:
        from django.conf import settings

        return getattr(settings, "LLM_PROVIDER", "openai")
    except Exception:
        return "openai"


def _call_openai(transcript, title):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMError("openai package is not installed.", retryable=False,
                       provider="openai") from exc
    try:
        from django.conf import settings

        api_key = getattr(settings, "OPENAI_API_KEY", "")
    except Exception:
        api_key = ""
    client = OpenAI(api_key=api_key or None, timeout=OPENAI_TIMEOUT_SEC)
    logger.info("llm call start: provider=openai title=%.60s chars=%d",
                title, len(transcript))
    started = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=3000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"TITLE: {title}\nTRANSCRIPT:\n{transcript}"},
            ],
        )
        payload = json.loads(resp.choices[0].message.content)
        logger.info("llm call done: provider=openai ms=%d",
                    int((time.perf_counter() - started) * 1000))
        return payload
    except LLMError:
        raise
    except Exception as exc:
        logger.warning("llm call failed: provider=openai err=%s", exc)
        raise LLMError(f"OpenAI call failed: {exc}", retryable=True,
                       provider="openai") from exc


def _call_gemini(transcript, title):
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise LLMError("google-generativeai is not installed.", retryable=False,
                       provider="gemini") from exc
    try:
        from django.conf import settings

        api_key = getattr(settings, "GEMINI_API_KEY", "")
    except Exception:
        api_key = ""
    logger.info("llm call start: provider=gemini title=%.60s chars=%d",
                title, len(transcript))
    started = time.perf_counter()
    try:
        genai.configure(api_key=api_key or None)
        model = genai.GenerativeModel(
            GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
            generation_config={"response_mime_type": "application/json",
                               "temperature": 0.3, "max_output_tokens": 3000},
        )
        # request_options timeout: without it a stalled generation hangs the
        # worker (and the UI) with no error, exactly like the transcript hang.
        resp = model.generate_content(
            f"TITLE: {title}\nTRANSCRIPT:\n{transcript}",
            request_options={"timeout": GEMINI_TIMEOUT_SEC},
        )
        payload = json.loads(resp.text)
        logger.info("llm call done: provider=gemini ms=%d",
                    int((time.perf_counter() - started) * 1000))
        return payload
    except LLMError:
        raise
    except Exception as exc:
        logger.warning("llm call failed: provider=gemini err=%s", exc)
        raise LLMError(f"Gemini call failed: {exc}", retryable=True,
                       provider="gemini") from exc


def _validate_shape(payload):
    if not isinstance(payload, dict):
        raise LLMError("LLM payload is not a JSON object.", retryable=False)
    for key in ("summary", "chapters", "keywords", "flashcards"):
        if key not in payload:
            raise LLMError(f"LLM payload missing key: {key}.", retryable=False)
    if not isinstance(payload["chapters"], list) or not payload["chapters"]:
        raise LLMError("LLM payload has no chapters.", retryable=False)
    return payload


def analyze_video(segments, title, provider=None, use_cache=True):
    """Run the LLM and return the validated raw payload (+_meta).

    Raises LLMError on failure / invalid JSON. Post-processing (chapter
    normalization, keyword re-scoring, degraded fallback) lives in
    services/chapterizer.py, services/text_metrics.py and
    apps/analytics/pipeline.py — never trust the LLM blindly.
    """
    full_text = " ".join(s.get("text", "") for s in (segments or []))
    key = cache_key(full_text)
    if use_cache and key in _cache:
        cached = dict(_cache[key])
        cached["_meta"] = {"cached": True, "degraded": False}
        return cached

    name = _provider_name(provider)
    caller = _call_gemini if name == "gemini" else _call_openai
    transcript = transcript_text(segments)
    last_error = LLMError("LLM call failed.", retryable=True, provider=name)
    for attempt in range(MAX_RETRIES + 1):
        try:
            payload = _validate_shape(caller(transcript, title))
            payload["_meta"] = {"cached": False, "degraded": False, "provider": name}
            if use_cache:
                _cache[key] = {k: v for k, v in payload.items() if k != "_meta"}
            return payload
        except LLMError as exc:
            last_error = exc
            if not exc.retryable:
                raise
            time.sleep(_backoff_delay(attempt))
    raise last_error


def clear_cache():
    """Test helper: empty the in-memory LLM cache."""
    _cache.clear()
