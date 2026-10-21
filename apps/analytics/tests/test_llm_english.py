"""Output-language constraint enforcement (LLM prompt contract).

Run: python apps/analytics/tests/test_llm_english.py (needs repo root on PYTHONPATH)

The user-selected transcript language now localizes the OUTPUT (summary,
chapters, keywords, flashcards, MCQs). Default remains English-first and
unknown codes must stay English. Proves the generated output-constraint
reaches both providers verbatim and that response parsers leave it alone.
SDKs are stubbed — no network, no keys.
"""
import json
import os
import sys
import types

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

ENGLISH_CONSTRAINT = "strictly in English"
HINDI_CONSTRAINT = "Hindi"


def test_default_prompt_carries_english_constraint():
    from services import llm_client

    instruction = llm_client.output_language_instruction("en")
    assert ENGLISH_CONSTRAINT in instruction
    assert "regardless of the transcript's language" in instruction


def test_unknown_language_defaults_to_english():
    from services import llm_client

    for bogus in ("", None, "xx", "h4x=DROP TABLE"):
        assert ENGLISH_CONSTRAINT in llm_client.output_language_instruction(bogus)


def test_selected_language_localizes_output():
    from services import llm_client

    instruction = llm_client.output_language_instruction("hi")
    assert HINDI_CONSTRAINT in instruction
    assert ENGLISH_CONSTRAINT not in instruction


def test_every_supported_language_localizes_output():
    from services import llm_client

    supported = {"en": "English", "es": "Spanish", "hi": "Hindi",
                 "fr": "French", "de": "German", "pt": "Portuguese"}
    assert llm_client.OUTPUT_LANGUAGE_NAMES == supported
    for code, name in supported.items():
        instruction = llm_client.output_language_instruction(code)
        assert name in instruction, code
        if code != "en":
            assert ENGLISH_CONSTRAINT not in instruction, code


def test_openai_system_message_keeps_constraint():
    from services import llm_client

    llm_client.clear_cache()
    captured = {}

    fake_openai = types.ModuleType("openai")

    class _Completions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            canned = {"summary": "सारांश।",
                      "chapters": [{"title": "परिचय", "start_sec": 0, "end_sec": 600,
                                    "summary": ""}],
                      "keywords": [], "flashcards": [],
                     "mcqs": [{"question": "P?", "options": ["A", "B", "C", "D"],
                               "answer_index": 1, "explanation": "E.", "timestamp_sec": 2}]}
            msg = types.SimpleNamespace(content=json.dumps(canned))
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    class _Chat:
        completions = _Completions()

    class _Client:
        def __init__(self, *a, **k):
            pass

        chat = _Chat()

    fake_openai.OpenAI = _Client
    real = dict(sys.modules)
    sys.modules["openai"] = fake_openai
    try:
        from django.test.utils import override_settings

        segs = [{"start": 0.0, "duration": 5.0,
                 "text": "पोर्टफोलियो डेटा विश्लेषण।"}]
        with override_settings(OPENAI_API_KEY="test-key"):
            payload = llm_client.analyze_video(
                segs, "T", provider="openai", use_cache=False, language="hi")
            hindi_msg = [m["content"] for m in captured["messages"]
                         if m["role"] == "system"][-1]
            assert HINDI_CONSTRAINT in hindi_msg
            # Same transcript, default English must still pin English output.
            llm_client.clear_cache()
            llm_client.analyze_video(
                segs, "T", provider="openai", use_cache=False, language="en")
            english_msg = [m["content"] for m in captured["messages"]
                           if m["role"] == "system"][-1]
            assert ENGLISH_CONSTRAINT in english_msg
    finally:
        sys.modules.clear()
        sys.modules.update(real)
    assert payload["summary"] == "सारांश।"


def test_gemini_instruction_keeps_constraint():
    from services import llm_client

    llm_client.clear_cache()
    captured = {"calls": []}
    fake_genai = types.ModuleType("google.genai")
    fake_types = types.ModuleType("google.genai.types")
    fake_types.HttpOptions = lambda **kw: types.SimpleNamespace(**kw)
    fake_types.ThinkingConfig = lambda **kw: types.SimpleNamespace(**kw)
    fake_types.GenerateContentConfig = lambda **kw: types.SimpleNamespace(**kw)

    class _Models:
        @staticmethod
        def generate_content(model=None, contents=None, config=None):
            captured["calls"].append({"model": model, "config": config})
            canned = {"summary": "सारांश।",
                      "chapters": [{"title": "परिचय", "start_sec": 0, "end_sec": 600,
                                    "summary": ""}],
                      "keywords": [], "flashcards": [],
                     "mcqs": [{"question": "P?", "options": ["A", "B", "C", "D"],
                               "answer_index": 1, "explanation": "E.", "timestamp_sec": 2}]}
            return types.SimpleNamespace(text=json.dumps(canned))

    class _Client:
        def __init__(self, *args, **kwargs):
            self.models = _Models()

    fake_genai.types = fake_types
    fake_genai.Client = _Client
    real = dict(sys.modules)
    sys.modules["google"] = types.ModuleType("google")
    sys.modules["google.genai"] = fake_genai
    sys.modules["google.genai.types"] = fake_types
    try:
        from django.test.utils import override_settings

        segs = [{"start": 0.0, "duration": 5.0,
                 "text": "पोर्टफोलियो डेटा विश्लेषण।"}]
        with override_settings(GEMINI_API_KEY="test-key"):
            payload = llm_client.analyze_video(
                segs, "T", provider="gemini", use_cache=False, language="hi")
        config = captured["calls"][0]["config"]
        assert HINDI_CONSTRAINT in captured["calls"][0]["config"].system_instruction
        assert config.thinking_config.thinking_level == "low"
    finally:
        sys.modules.clear()
        sys.modules.update(real)
    assert payload["summary"] == "सारांश।"


def test_gemini_falls_back_when_primary_model_fails():
    from services import llm_client

    llm_client.clear_cache()
    models_used = []
    fake_genai = types.ModuleType("google.genai")
    fake_types = types.ModuleType("google.genai.types")
    fake_types.HttpOptions = lambda **kw: types.SimpleNamespace(**kw)
    fake_types.ThinkingConfig = lambda **kw: types.SimpleNamespace(**kw)
    fake_types.GenerateContentConfig = lambda **kw: types.SimpleNamespace(**kw)

    class _Models:
        @staticmethod
        def generate_content(model=None, contents=None, config=None):
            models_used.append(model)
            if model == llm_client.GEMINI_MODEL:
                raise RuntimeError("504 Deadline expired before operation could complete.")
            canned = {"summary": "S",
                      "chapters": [{"title": "Intro", "start_sec": 0, "end_sec": 600,
                                    "summary": ""}],
                      "keywords": [], "flashcards": [],
                     "mcqs": [{"question": "Q?", "options": ["A", "B", "C", "D"],
                               "answer_index": 1, "explanation": "E.", "timestamp_sec": 2}]}
            return types.SimpleNamespace(text=json.dumps(canned))

    class _Client:
        def __init__(self, *args, **kwargs):
            self.models = _Models()

    fake_genai.types = fake_types
    fake_genai.Client = _Client
    real = dict(sys.modules)
    sys.modules["google"] = types.ModuleType("google")
    sys.modules["google.genai"] = fake_genai
    sys.modules["google.genai.types"] = fake_types
    try:
        from django.test.utils import override_settings

        segs = [{"start": 0.0, "duration": 5.0, "text": "alpha beta"}]
        with override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL=llm_client.GEMINI_MODEL):
            llm_client.analyze_video(segs, "T", provider="gemini",
                                     use_cache=False, language="en")
    finally:
        sys.modules.clear()
        sys.modules.update(real)
    assert models_used[0] == llm_client.GEMINI_MODEL
    assert models_used[-1] == llm_client.GEMINI_FALLBACK_MODEL


def test_cache_keys_are_language_scoped():
    from services import llm_client

    assert llm_client.cache_key("abc") == llm_client.cache_key("abc")
    llm_client.clear_cache()
    key_hi = ("hi", llm_client.cache_key("abc"))
    key_en = ("en", llm_client.cache_key("abc"))
    llm_client._cache[key_hi] = {"summary": "हिंदी"}
    assert llm_client._cache.get(key_en) is None
    llm_client.clear_cache()


def test_parsers_do_not_touch_prompt_contract():
    from services import llm_client
    from services.llm_client import LLMError

    good = {"summary": "S",
            "chapters": [{"title": "A", "start_sec": 0, "end_sec": 5, "summary": ""}],
            "keywords": [], "flashcards": [],
                     "mcqs": [{"question": "Q?", "options": ["A", "B", "C", "D"],
                               "answer_index": 1, "explanation": "E.", "timestamp_sec": 2}]}
    assert llm_client._validate_shape(dict(good))["summary"] == "S"
    try:
        llm_client._validate_shape({"summary": "S"})
    except LLMError:
        pass
    else:
        raise AssertionError("shape validation must still reject missing keys")


if __name__ == "__main__":
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    print("ALL OUTPUT-LANGUAGE CHECKS PASSED")
