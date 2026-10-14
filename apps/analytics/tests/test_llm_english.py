"""English-only output enforcement (LLM prompt constraint).

Run: python apps/analytics/tests/test_llm_english.py (needs repo root on PYTHONPATH)
Proves the CRITICAL CONSTRAINT reaches both providers verbatim and that
response parsers leave it alone. SDKs are stubbed — no network, no keys.
"""
import json
import os
import sys
import types

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

CONSTRAINT = "strictly in English"


def test_prompt_carries_english_constraint():
    from services import llm_client

    assert CONSTRAINT in llm_client.SYSTEM_PROMPT
    assert "regardless of the input language" in llm_client.SYSTEM_PROMPT


def test_openai_system_message_keeps_constraint():
    from services import llm_client

    llm_client.clear_cache()
    captured = {}

    fake_openai = types.ModuleType("openai")

    class _Completions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            canned = {"summary": "English summary.",
                      "chapters": [{"title": "Intro", "start_sec": 0, "end_sec": 600,
                                    "summary": ""}],
                      "keywords": [], "flashcards": [],
                     "mcqs": [{"question": "Q?", "options": ["A", "B", "C", "D"],
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
            llm_client.analyze_video(segs, "T", provider="openai", use_cache=False)
    finally:
        sys.modules.clear()
        sys.modules.update(real)
    system_msgs = [m["content"] for m in captured["messages"] if m["role"] == "system"]
    assert any(CONSTRAINT in m for m in system_msgs), system_msgs


def test_gemini_instruction_keeps_constraint():
    from services import llm_client

    llm_client.clear_cache()
    captured = {}
    module = types.ModuleType("google.generativeai")
    module.configure = lambda api_key=None: None

    class _Model:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def generate_content(self, prompt, **kwargs):
            canned = {"summary": "English summary.",
                      "chapters": [{"title": "Intro", "start_sec": 0, "end_sec": 600,
                                    "summary": ""}],
                      "keywords": [], "flashcards": [],
                     "mcqs": [{"question": "Q?", "options": ["A", "B", "C", "D"],
                               "answer_index": 1, "explanation": "E.", "timestamp_sec": 2}]}
            return types.SimpleNamespace(text=json.dumps(canned))

    module.GenerativeModel = _Model
    real = dict(sys.modules)
    sys.modules["google.generativeai"] = module
    sys.modules.setdefault("google", types.ModuleType("google"))
    try:
        from django.test.utils import override_settings

        segs = [{"start": 0.0, "duration": 5.0,
                 "text": "पोर्टफोलियो डेटा विश्लेषण।"}]
        with override_settings(GEMINI_API_KEY="test-key"):
            llm_client.analyze_video(segs, "T", provider="gemini", use_cache=False)
    finally:
        sys.modules.clear()
        sys.modules.update(real)
    assert CONSTRAINT in captured.get("system_instruction", "")


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
    print("ALL ENGLISH-ONLY CHECKS PASSED")
