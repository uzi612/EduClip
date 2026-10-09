"""LLM provider selection + Gemini default (gemini-1.5-flash).

Run: python apps/analytics/tests/test_llm_providers.py (needs repo root on PYTHONPATH)
google.generativeai is stubbed via sys.modules — no network, no key needed.
"""
import json
import os
import sys
import types
from unittest.mock import patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()

from django.test.utils import override_settings  # noqa: E402

from services import llm_client
from services.llm_client import LLMError

SEGS = [{"start": 0.0, "duration": 5.0, "text": "alpha beta"}]
CANNED = {
    "summary": "S.",
    "chapters": [{"title": "A", "start_sec": 0, "end_sec": 600, "summary": ""}],
    "keywords": [{"term": "alpha", "score": 0.9}],
    "flashcards": [{"front": "Q?", "back": "A.", "timestamp_sec": 1}],
}
CAPTURED = {}


def _install_genai_stub():
    module = types.ModuleType("google.generativeai")

    def configure(api_key=None):
        CAPTURED["api_key"] = api_key

    class _Model:
        def __init__(self, *args, **kwargs):
            CAPTURED["model_args"] = (args, kwargs)

        def generate_content(self, prompt):
            CAPTURED["prompt"] = prompt
            return types.SimpleNamespace(text=json.dumps(CANNED))

    module.configure = configure
    module.GenerativeModel = _Model
    return module


def test_default_provider_is_gemini():
    assert llm_client._provider_name() == "gemini"
    assert llm_client._provider_name("openai") == "openai"


def test_missing_gemini_key_is_clear_and_terminal():
    llm_client.clear_cache()
    with override_settings(GEMINI_API_KEY=""):
        try:
            llm_client._call_gemini("t", "T")
        except LLMError as exc:
            assert "GEMINI_API_KEY" in str(exc) and exc.retryable is False
            assert exc.provider == "gemini"
            return
    raise AssertionError("expected LLMError naming GEMINI_API_KEY")


def test_missing_openai_key_is_clear_and_terminal():
    llm_client.clear_cache()
    with override_settings(OPENAI_API_KEY=""):
        try:
            llm_client._call_openai("t", "T")
        except LLMError as exc:
            assert "OPENAI_API_KEY" in str(exc) and exc.retryable is False
            return
    raise AssertionError("expected LLMError naming OPENAI_API_KEY")


def test_gemini_path_returns_identical_schema():
    llm_client.clear_cache()
    stub = _install_genai_stub()
    real_modules = dict(sys.modules)
    sys.modules["google.generativeai"] = stub
    sys.modules.setdefault("google", types.ModuleType("google"))
    try:
        with override_settings(GEMINI_API_KEY="test-key", LLM_PROVIDER="gemini"):
            out = llm_client.analyze_video(SEGS, "T", use_cache=False)
    finally:
        sys.modules.clear()
        sys.modules.update(real_modules)
    assert set(("summary", "chapters", "keywords", "flashcards")) <= set(out)
    assert out["_meta"]["provider"] == "gemini" and CAPTURED["api_key"] == "test-key"
    assert CAPTURED["model_args"][0][0] == llm_client.GEMINI_MODEL
    assert "TITLE: T" in CAPTURED["prompt"]


if __name__ == "__main__":
    for name, fn in sorted([(k, v) for k, v in globals().items() if k.startswith("test_")]):
        fn()
        print(f"PASS {name}")
    print("ALL LLM PROVIDER CHECKS PASSED")
