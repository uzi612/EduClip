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
GEMINI_TIMEOUT_SEC = 120
GEMINI_TIMEOUT_MS = GEMINI_TIMEOUT_SEC * 1000
# Fallback default only — settings.GEMINI_MODEL (env GEMINI_MODEL) wins, since
# identifiers rot (2.5-flash retired for new keys; 3.8-flash chronically 504s —
# live-verified Oct 2026 — while 3.5-flash-lite answers in ~1.6s).
GEMINI_MODEL = "gemini-3.5-flash-lite"
# Room for Gemini 3.x thinking tokens on top of the JSON body; the old 3000
# budget combined the two and truncated long-ish payloads into invalid JSON.
GEMINI_MAX_OUTPUT_TOKENS = 6000
# Stable sibling used when GEMINI_MODEL 504s/flakes (live-verified Oct 2026).
GEMINI_FALLBACK_MODEL = "gemini-3.5-flash"
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
  "back": str (answer, <=300 chars), "timestamp_sec": int,
  "difficulty": "easy"|"medium"|"hard",
  "tags": [0-2 short topical tags, each <=30 chars]}].
  Ask at least 5 content-grounded questions (no generic filler like "What is
  the main idea?"); every card must be answerable from the transcript.
  Spread the card timestamps across the whole video: at least one card per
  chapter, never clustered on a single section.
- mcqs: 4-5 items [{"question": str (<=200 chars),
  "options": [exactly 4 answer strings, each <=200 chars],
  "answer_index": int 0-3 pointing at the single correct option,
  "explanation": str (<=500 chars, why the answer is right),
  "timestamp_sec": int}]. Distractors must be plausible but clearly wrong
  given the video; vary the correct position across questions.
Return JSON only, no markdown fences.
An output-language constraint is appended to this prompt; obey it for every generated text. DO NOT invent extra keys."""

OUTPUT_LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "hi": "Hindi",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
}


def output_language_instruction(language):
    """Prompt line controlling the OUTPUT language of every generated text.

    The deliberate default keeps production output English-first (the original
    contract); callers pass the user-selected transcript language to localize
    the whole dashboard locally — no second LLM round-trip.
    """
    lang = (language or "en").strip().lower()[:10]
    if not lang or lang == "en" or lang not in OUTPUT_LANGUAGE_NAMES:
        return ("CRITICAL OUTPUT CONSTRAINT: Write every text field (summary, "
                "chapter titles and summaries, key terms, flashcard fronts and "
                "backs, MCQ questions, options, and explanations) strictly in "
                "English, regardless of the transcript's language.")
    return (
        f"CRITICAL OUTPUT CONSTRAINT: The user selected {OUTPUT_LANGUAGE_NAMES[lang]}. "
        f"Write every text field (summary, chapter titles and summaries, key "
        f"terms, flashcard fronts and backs, MCQ questions, options, and "
        f"explanations) in natural, learner-friendly {OUTPUT_LANGUAGE_NAMES[lang]}. "
        f"Keep the JSON keys and integer fields exactly as specified; only the "
        f"human-readable strings are written in {OUTPUT_LANGUAGE_NAMES[lang]}. "
        f"If the transcript is already in "
        f"{OUTPUT_LANGUAGE_NAMES[lang]}, still polish the output into that language."
    )


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


def _call_openai(transcript, title, language="en"):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMError("openai package is not installed.", retryable=False,
                       provider="openai") from exc
    try:
        from django.conf import settings

        api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    except Exception:
        api_key = ""
    if not api_key:
        raise LLMError(
            "OPENAI_API_KEY is not configured. Set it in .env (see .env.example) "
            "or switch provider with LLM_PROVIDER=gemini plus GEMINI_API_KEY.",
            retryable=False, provider="openai",
        )
    client = OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SEC)
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
                {"role": "system",
                 "content": SYSTEM_PROMPT + "\n" + output_language_instruction(language)},
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


def _gemini_model_candidates():
    """Configured model first, then a stable fallback if the primary flakes."""
    try:
        from django.conf import settings as _dj_settings

        model_id = getattr(_dj_settings, "GEMINI_MODEL", "") or GEMINI_MODEL
    except Exception:
        model_id = GEMINI_MODEL
    models = [model_id]
    if GEMINI_FALLBACK_MODEL and model_id != GEMINI_FALLBACK_MODEL:
        models.append(GEMINI_FALLBACK_MODEL)
    return models


def _call_gemini_model(client, model_id, prompt, system):
    from google.genai import types as genai_types

    try:
        from django.conf import settings as _dj_settings

        model_version = _dj_settings.GEMINI_MODEL or GEMINI_MODEL
    except Exception:
        model_version = GEMINI_MODEL
    model_family = model_id or model_version
    temperature = None if model_family.startswith(("gemini-3", "gemini-4")) else 0.3
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
        thinking_config=genai_types.ThinkingConfig(thinking_level="low")
        if model_family.startswith(("gemini-3", "gemini-4")) else None,
    )
    if temperature is not None:
        config.temperature = temperature
    resp = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=config,
    )
    text = (getattr(resp, "text", "") or "").strip()
    if not text:
        raise LLMError(f"Gemini returned an empty payload for {model_id}.",
                       retryable=True, provider="gemini")
    return json.loads(text)


def _call_gemini(transcript, title, language="en"):
    """Modern google-genai path (google-generativeai is dead — 504-prone).

    Two concrete fixes for the 504 'Deadline expired' stream: the old SDK used
    the model's default 'medium' thinking on an unbounded deadline, so a long
    transcript died at 60s and the degraded (English) fallback won. Now:
    thinking_level='low' for Gemini 3.x, a hard 120s HTTP deadline, and a
    stable fallback model when the primary one flakes.
    """
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as exc:
        raise LLMError("google-genai is not installed (pip install google-genai).",
                       retryable=False, provider="gemini") from exc
    try:
        from django.conf import settings

        api_key = getattr(settings, "GEMINI_API_KEY", "") or ""
    except Exception:
        api_key = ""
    if not api_key:
        raise LLMError(
            "GEMINI_API_KEY is not configured. Set it in .env (see .env.example) "
            "to generate video insights.",
            retryable=False, provider="gemini",
        )
    system = SYSTEM_PROMPT + "\n" + output_language_instruction(language)
    prompt = f"TITLE: {title}\nTRANSCRIPT:\n{transcript}"
    client = genai.Client(
        api_key=api_key,
        http_options=genai_types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
    )
    started = time.perf_counter()
    last_error = None
    for model_id in _gemini_model_candidates():
        logger.info("llm call start: provider=gemini model=%s title=%.60s chars=%d",
                    model_id, title, len(transcript))
        try:
            payload = _call_gemini_model(client, model_id, prompt, system)
            logger.info("llm call done: provider=gemini model=%s ms=%d",
                        model_id, int((time.perf_counter() - started) * 1000))
            return payload
        except LLMError:
            raise
        except Exception as exc:
            msg = str(exc)
            retryable = not ("API key" in msg or "api_key" in msg)
            last_error = LLMError(f"Gemini call failed ({model_id}): {msg}",
                                  retryable=retryable, provider="gemini")
            logger.warning("llm call failed: provider=gemini model=%s err=%s",
                           model_id, msg)
    raise last_error


def _validate_shape(payload):
    if not isinstance(payload, dict):
        raise LLMError("LLM payload is not a JSON object.", retryable=False)
    for key in ("summary", "chapters", "keywords", "flashcards", "mcqs"):
        if key not in payload:
            raise LLMError(f"LLM payload missing key: {key}.", retryable=False)
    if not isinstance(payload["chapters"], list) or not payload["chapters"]:
        raise LLMError("LLM payload has no chapters.", retryable=False)
    if not isinstance(payload.get("mcqs"), list) or not payload["mcqs"]:
        raise LLMError("LLM payload has no mcqs.", retryable=False)
    return payload


DIFFICULTIES = ("easy", "medium", "hard")


def clean_flashcard(raw):
    """Validate one raw flashcard dict. Returns a clean dict or None to drop.

    Mirrors the mongoengine Flashcard field limits (front<=140, back<=300,
    tags<=30 chars) so pipeline output can persist without silent truncation
    surprises. Unknown/garbled difficulty degrades to "medium", tags are
    whitespace-trimmed, deduped case-insensitively and capped at 3.
    """
    if not isinstance(raw, dict):
        return None
    front = " ".join(str(raw.get("front", "")).split())[:140]
    back = " ".join(str(raw.get("back", "")).split())[:300]
    if not front or not back:
        return None
    try:
        ts = max(0, int(float(raw.get("timestamp_sec", 0))))
    except (TypeError, ValueError):
        ts = 0
    difficulty = str(raw.get("difficulty", "medium")).strip().lower()
    if difficulty not in DIFFICULTIES:
        difficulty = "medium"
    tags, seen = [], set()
    for tag in (raw.get("tags") or [])[:3]:
        tag = " ".join(str(tag).split())
        if not tag or len(tag) > 30:
            continue  # oversized tags are model noise — drop, don't truncate
        if tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    return {"front": front, "back": back, "timestamp_sec": ts,
            "difficulty": difficulty, "tags": tags}


def clean_mcq(item):
    """Validate one raw MCQ dict. Returns a clean dict or None to drop it."""
    if not isinstance(item, dict):
        return None
    question = " ".join(str(item.get("question", "")).split())[:200]
    options = [" ".join(str(o).split())[:200] for o in (item.get("options") or [])]
    options = [o for o in options if o][:4]
    explanation = " ".join(str(item.get("explanation", "")).split())[:500]
    try:
        answer = int(item.get("answer_index", -1))
        ts = max(0, int(float(item.get("timestamp_sec", 0))))
    except (TypeError, ValueError):
        return None
    if not question or len(options) != 4 or not explanation:
        return None
    if answer not in (0, 1, 2, 3):
        return None
    return {"question": question, "options": options, "answer_index": answer,
            "explanation": explanation, "timestamp_sec": ts}


def analyze_video(segments, title, provider=None, use_cache=True, language="en"):
    """Run the LLM and return the validated raw payload (+_meta).

    Raises LLMError on failure / invalid JSON. Post-processing (chapter
    normalization, keyword re-scoring, degraded fallback) lives in
    services/chapterizer.py, services/text_metrics.py and
    apps/analytics/pipeline.py — never trust the LLM blindly.
    `language` controls the OUTPUT language of every generated text field
    (summary, chapters, keywords, flashcards, MCQs), not just the transcript.
    """
    full_text = " ".join(s.get("text", "") for s in (segments or []))
    lang = (language or "en").strip().lower()[:10]
    key = (lang, cache_key(full_text))
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
            payload = _validate_shape(caller(transcript, title, language=lang))
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
