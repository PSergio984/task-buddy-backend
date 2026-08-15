"""Tests for the OpenAI embedding provider (app/knowledge/embeddings.py).

The local-provider path is covered by the autouse mock_embedder fixture; these
tests flip the provider constant and stub the OpenAI client instead.
"""

import numpy as np
import pytest

import app.knowledge.embeddings as embeddings_module
from app.config import EMBEDDING_DIM


def _fake_openai_response(vectors: list[list[float]]) -> object:
    class _Data:
        def __init__(self, embedding: list[float]) -> None:
            self.embedding = embedding

    class _Response:
        def __init__(self) -> None:
            self.data = [_Data(v) for v in vectors]

    return _Response()


class _FakeEmbeddings:
    def __init__(self, calls: list[tuple[str, list[str]]], vectors: list[list[float]]) -> None:
        self.calls = calls
        self.vectors = vectors

    def create(self, model: str, input: list[str]):
        self.calls.append((model, input))
        return _fake_openai_response(self.vectors)


class _FakeClient:
    def __init__(self, calls: list[tuple[str, list[str]]], vectors: list[list[float]]) -> None:
        self.embeddings = _FakeEmbeddings(calls, vectors)


@pytest.fixture(autouse=True)
def _openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run these tests against the openai provider regardless of config."""
    monkeypatch.setattr(embeddings_module, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(embeddings_module, "OPENAI_API_KEY", "sk-test")


def test_embed_openai_calls_api_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed_texts hits the OpenAI client and returns L2-normalized vectors."""
    raw = [
        [3.0, 0.0, 0.0, 0.0] + [0.0] * (EMBEDDING_DIM - 4),
        [0.0, 4.0, 0.0, 0.0] + [0.0] * (EMBEDDING_DIM - 4),
    ]
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(embeddings_module, "_openai_client", lambda: _FakeClient(calls, raw))

    out = embeddings_module.embed_texts(["alpha", "beta"])

    assert calls == [("text-embedding-3-small", ["alpha", "beta"])]
    assert out.shape == (2, EMBEDDING_DIM)
    # L2-normalized: each row has unit norm
    norms = np.linalg.norm(out, axis=1)
    np.testing.assert_allclose(norms, np.ones(2), atol=1e-6)


def test_embed_openai_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty input returns an empty (0, EMBEDDING_DIM) array without an API call."""

    def _boom(*_args, **_kwargs) -> None:
        raise AssertionError("API must not be called for empty input")

    monkeypatch.setattr(embeddings_module, "_openai_client", _boom)

    out = embeddings_module.embed_texts([])
    assert out.shape == (0, EMBEDDING_DIM)
