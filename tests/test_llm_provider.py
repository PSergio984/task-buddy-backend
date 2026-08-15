"""Tests for the provider-switchable LLM client (app/knowledge/assistant.py).

Dev/test default to the openai provider; these tests flip to groq and verify
the client construction, model selection, and cost rates follow the active
provider.
"""

import pytest

import app.knowledge.assistant as assistant_module
from app.knowledge import cost as cost_module


def test_groq_provider_builds_client_with_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Groq is reached through the OpenAI SDK with its compatible base_url."""
    monkeypatch.setattr(assistant_module, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(assistant_module, "GROQ_API_KEY", "gsk-test")

    captured: dict[str, str] = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(assistant_module, "OpenAI", _FakeOpenAI)

    assistant_module._openai_client()

    assert captured["api_key"] == "gsk-test"
    assert captured["base_url"] == "https://api.groq.com/openai/v1"


def test_groq_missing_key_raises_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing GROQ_API_KEY surfaces as AssistantNotConfiguredError (503)."""
    monkeypatch.setattr(assistant_module, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(assistant_module, "GROQ_API_KEY", None)

    with pytest.raises(assistant_module.AssistantNotConfiguredError, match="GROQ_API_KEY"):
        assistant_module._openai_client()


def test_openai_provider_uses_openai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The openai provider builds a plain OpenAI client."""
    monkeypatch.setattr(assistant_module, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(assistant_module, "OPENAI_API_KEY", "sk-test")

    captured: dict[str, str] = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(assistant_module, "OpenAI", _FakeOpenAI)

    assistant_module._openai_client()

    assert captured["api_key"] == "sk-test"
    assert "base_url" not in captured


def test_llm_model_follows_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """_llm_model returns the groq model under the groq provider."""
    monkeypatch.setattr(assistant_module, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(assistant_module, "GROQ_MODEL", "llama-3.3-70b-versatile")
    assert assistant_module._llm_model() == "llama-3.3-70b-versatile"

    monkeypatch.setattr(assistant_module, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(assistant_module, "OPENAI_MODEL", "gpt-4o-mini")
    assert assistant_module._llm_model() == "gpt-4o-mini"


def test_calculate_cost_uses_groq_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cost uses the active provider's per-1M-token rates."""
    monkeypatch.setattr(cost_module, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(cost_module, "GROQ_INPUT_RATE_PER_1M", 0.59)
    monkeypatch.setattr(cost_module, "GROQ_OUTPUT_RATE_PER_1M", 0.79)

    # 1M input tokens + 1M output tokens = $0.59 + $0.79
    assert cost_module.calculate_cost(1_000_000, 1_000_000) == pytest.approx(1.38)

    monkeypatch.setattr(cost_module, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(cost_module, "OPENAI_INPUT_RATE_PER_1M", 0.15)
    monkeypatch.setattr(cost_module, "OPENAI_OUTPUT_RATE_PER_1M", 0.60)
    assert cost_module.calculate_cost(1_000_000, 1_000_000) == pytest.approx(0.75)
