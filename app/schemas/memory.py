"""Response schemas for the Memory API (POST /api/v1/tasks/{task_id}/memory/similar)."""

from pydantic import BaseModel, Field


class SimilarTaskRow(BaseModel):
    """One similar completed task — raw row + retrieval score, no LLM fields (D-08)."""

    id: int  # task_id (task-level dedupe: best rrf_score per task)
    title: str
    duration_minutes: float  # from TaskKnowledge.extra_metadata["duration_minutes"]
    rrf_score: float
    chunk_text: str


class MemorySimilarResponse(BaseModel):
    """Raw-rows response for a /memory/similar query."""

    task_id: int  # the query task
    similar_tasks: list[SimilarTaskRow] = Field(default_factory=list)
    response_time_ms: float  # latency-only instrumentation (D-09)
