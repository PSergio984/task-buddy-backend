"""Neutral record/citation shapes shared by the assistant and persistence layers.

Lives outside ``assistant.py`` so ``app.crud.knowledge`` can depend on the
record type without importing the assistant module — ARCHITECTURE.md flags
circular imports between layers as a known risk. The module deliberately hosts
two related shapes: the per-call metrics record (``LLMCallRecord``) and the
persisted citation shape (``normalize_citation``/``normalize_citations``) —
both are contracts between the assistant and the persistence layer, and
keeping them here (rather than in either consumer) is what breaks the cycle.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class LLMCallRecord:
    """Everything we keep about one LLM call (llm-zc field-for-field)."""

    model: str
    prompt: str
    instructions: str
    answer: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    response_time: float
    cost: float
    timestamp: datetime = field(default_factory=datetime.now)


def normalize_citation(chunk: dict[str, Any]) -> dict[str, Any] | None:
    """Reduce an already-resolved chunk to the canonical citation shape.

    Accepts a dict carrying an explicit ``knowledge_id`` (raw search chunks
    with only a ``chunk_id`` do NOT qualify — a chunk id is not a knowledge
    id, RESEARCH §7) and emits ``{knowledge_id, chunk_text, rrf_score}``.
    Unresolvable chunks return ``None`` rather than minting a fabricated id.
    """
    knowledge_id = chunk.get("knowledge_id")
    if knowledge_id is None:
        return None
    return {
        "knowledge_id": knowledge_id,
        "chunk_text": chunk.get("chunk_text") or chunk.get("text") or "",
        "rrf_score": float(chunk.get("rrf_score") or 0.0),
    }


def normalize_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map a list of raw chunks to canonical citations, dropping unresolvable ones."""
    return [
        citation
        for citation in (normalize_citation(chunk) for chunk in chunks)
        if citation is not None
    ]
