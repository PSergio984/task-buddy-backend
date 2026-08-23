"""Task-breakdown proposal service (POST /api/v1/breakdown).

Turns a typed or pasted text blob into proposed tasks + subtasks via one
structured-output LLM call. Proposals are stateless: nothing is persisted
here — the router persists telemetry only, the client holds the draft.

Quality rules (wayfinder ticket "Grill: prompt design and quality bar"):
max 15 tasks per proposal, 3-7 subtasks per task, never invent tasks not
implied by the input, titles-only output plus optional task-level effort.
"""

import asyncio
import json
import logging
import time
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BREAKDOWN_MODEL
from app.knowledge import assistant
from app.knowledge.records import LLMCallRecord
from app.knowledge.retrieval import UserKnowledgeIndex
from app.models.knowledge import KnowledgeChunk, SourceType, TaskKnowledge

logger = logging.getLogger(__name__)

MAX_TASKS_PER_PROPOSAL = 15
MIN_SUBTASKS_PER_TASK = 3
MAX_SUBTASKS_PER_TASK = 7
# Server-side clamp mirroring the client character counter; protects both the
# model context window and the output-token budget on free-tier Groq.
INPUT_CHAR_LIMIT = 10_000
MEMORY_HINT_LIMIT = 3
# gpt-oss models are reasoners: reasoning tokens bill as completion tokens, so
# the free-tier TPM budget needs a hard output ceiling and low effort.
MAX_COMPLETION_TOKENS = 4096
REASONING_EFFORT = "low"

BREAKDOWN_SYSTEM_PROMPT = (
    "You break a user's task notes into an actionable breakdown.\n"
    "Rules:\n"
    f"- At most {MAX_TASKS_PER_PROPOSAL} tasks; one blob may contain several tasks.\n"
    f"- Each task gets {MIN_SUBTASKS_PER_TASK}-{MAX_SUBTASKS_PER_TASK} concrete subtasks "
    "(fewer only when the task truly cannot be split).\n"
    "- Never invent tasks that are not implied by the input text.\n"
    "- Keep the user's own wording; subtask titles are short imperatives.\n"
    "- Set estimated_effort_minutes only when the text implies effort; otherwise null.\n"
    "- If the input contains no tasks at all, return {\"tasks\": []}.\n"
)

BREAKDOWN_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "breakdown_proposal",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "estimated_effort_minutes": {
                                "type": ["integer", "null"],
                            },
                            "subtasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"title": {"type": "string"}},
                                    "required": ["title"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["title", "estimated_effort_minutes", "subtasks"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["tasks"],
            "additionalProperties": False,
        },
    },
}


class BreakdownSubtaskProposal(BaseModel):
    """One proposed subtask row."""

    title: str


class BreakdownTaskProposal(BaseModel):
    """One proposed task with its ordered subtasks."""

    title: str
    subtasks: list[BreakdownSubtaskProposal] = Field(default_factory=list)
    # tbl_tasks.estimated_effort_minutes accepts 1..10080; out-of-range values
    # are dropped at parse time rather than rejected wholesale.
    estimated_effort_minutes: Optional[int] = Field(default=None, ge=1, le=10080)


class BreakdownProposal(BaseModel):
    """Parse-degraded proposal returned to the client."""

    tasks: list[BreakdownTaskProposal] = Field(default_factory=list)
    reason: Optional[str] = None


def build_breakdown_prompt(
    text: str,
    context_title: Optional[str] = None,
    context_description: Optional[str] = None,
    memory_hints: Optional[list[str]] = None,
    focus_task_title: Optional[str] = None,
) -> str:
    """Serialize input text (+optional per-task context, +memory hints)."""
    clamped = text[:INPUT_CHAR_LIMIT]
    parts: list[str] = []
    if context_title:
        parts.append(f"Context task: {context_title}")
        description = (context_description or "").strip()
        if description:
            parts.append(f"Context description: {description}")
    if focus_task_title:
        parts.append(
            "Refine request: regenerate the breakdown for this one task only:\n"
            f"<focus>{focus_task_title}</focus>"
        )
    parts.append("Input:")
    parts.append("<input>")
    parts.append(clamped)
    parts.append("</input>")
    if memory_hints:
        rendered = "\n".join(f"- {hint}" for hint in memory_hints)
        parts.append(f"Similar past tasks (style reference only):\n{rendered}")
    return "\n\n".join(parts)


def _clean_title(value: Any) -> str:
    return str(value or "").strip()


def parse_proposal(answer_text: str) -> BreakdownProposal:
    """Strict-parse the model output; degrade to empty-with-reason, never raise."""
    try:
        raw = json.loads(answer_text)
        tasks_raw = raw["tasks"]
        if not isinstance(tasks_raw, list):
            raise ValueError("tasks is not a list")
    except Exception as exc:
        logger.warning("breakdown parse failure: %s", exc)
        return BreakdownProposal(tasks=[], reason="breakdown could not be generated")

    tasks: list[BreakdownTaskProposal] = []
    for item in tasks_raw:
        if not isinstance(item, dict):
            continue
        title = _clean_title(item.get("title"))
        if not title:
            continue
        effort_raw = item.get("estimated_effort_minutes")
        try:
            effort = int(effort_raw) if effort_raw is not None else None
        except (TypeError, ValueError):
            effort = None
        if effort is not None and not (1 <= effort <= 10080):
            effort = None
        subtasks = [
            BreakdownSubtaskProposal(title=sub_title)
            for sub in item.get("subtasks") or []
            if isinstance(sub, dict) and (sub_title := _clean_title(sub.get("title")))
        ]
        tasks.append(
            BreakdownTaskProposal(
                title=title,
                subtasks=subtasks[:MAX_SUBTASKS_PER_TASK],
                estimated_effort_minutes=effort,
            )
        )
        if len(tasks) >= MAX_TASKS_PER_PROPOSAL:
            break
    return BreakdownProposal(tasks=tasks)


async def fetch_memory_hints(db: AsyncSession, user_id: int, text: str) -> list[str]:
    """Top-k similar completed-task titles from the user's knowledge index.

    Best-effort grounding: any failure (empty index, embedding provider down)
    degrades silently to no hints — the breakdown must never 5xx because of it.
    """
    try:
        chunks = await UserKnowledgeIndex().search(
            db, user_id, text[:500], limit=MEMORY_HINT_LIMIT * 3
        )
        if not chunks:
            return []
        chunk_ids = [c["chunk_id"] for c in chunks]
        result = await db.execute(
            select(TaskKnowledge.title)
            .join(KnowledgeChunk, KnowledgeChunk.knowledge_id == TaskKnowledge.id)
            .where(
                KnowledgeChunk.id.in_(chunk_ids),
                TaskKnowledge.source_type == SourceType.HISTORY,
                TaskKnowledge.user_id == user_id,
                TaskKnowledge.title.isnot(None),
            )
        )
        hints: list[str] = []
        for (title,) in result.all():
            clean = _clean_title(title)
            if clean and clean not in hints:
                hints.append(clean)
            if len(hints) >= MEMORY_HINT_LIMIT:
                break
        return hints
    except Exception:
        logger.debug("breakdown memory hints unavailable", exc_info=True)
        return []


async def generate_breakdown(
    prompt: str,
) -> tuple[BreakdownProposal, LLMCallRecord, str]:
    """One structured-output call; returns (proposal, record, raw answer)."""
    start = time.monotonic()
    response = await asyncio.to_thread(
        assistant._call_completion,
        BREAKDOWN_MODEL,
        [
            {"role": "system", "content": BREAKDOWN_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        BREAKDOWN_RESPONSE_FORMAT,
        MAX_COMPLETION_TOKENS,
        REASONING_EFFORT,
    )
    response_time = time.monotonic() - start

    answer_text = response.choices[0].message.content or ""
    usage = response.usage
    record = LLMCallRecord(
        model=BREAKDOWN_MODEL,
        prompt=prompt,
        instructions=BREAKDOWN_SYSTEM_PROMPT,
        answer=answer_text,
        prompt_tokens=getattr(usage, "prompt_tokens", 0),
        completion_tokens=getattr(usage, "completion_tokens", 0),
        total_tokens=getattr(usage, "total_tokens", 0),
        response_time=response_time,
        cost=0.0,
    )
    return parse_proposal(answer_text), record, answer_text
