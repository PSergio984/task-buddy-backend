"""Smart Import extraction service (POST /api/v1/import/extract).

Turns pasted freeform notes (meeting dumps, brain dumps) into task proposals
via one structured-output LLM call. Proposals are stateless: nothing is
persisted here — the router persists telemetry only, the client holds the
draft (spec #91, issue #92).

Extraction semantics differ from /breakdown's split-everything contract:
only ACTIONABLE items become proposals — context, musings, and FYI lines are
skipped — and each proposal carries deadline/priority/project hints resolved
against server-side state (today's UTC date, the user's existing projects).
"""

import asyncio
import json
import logging
import time
from collections.abc import Collection, Sequence
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.config import BREAKDOWN_MODEL
from app.knowledge import assistant
from app.knowledge.records import LLMCallRecord
from app.models.task import TaskPriority

logger = logging.getLogger(__name__)

MAX_PROPOSALS = 15
MAX_SUBTASKS_PER_PROPOSAL = 7
# Same 10k cap as breakdown — one shared input ceiling for pasted notes.
INPUT_CHAR_LIMIT = 10_000
# gpt-oss models are reasoners: reasoning tokens bill as completion tokens, so
# the free-tier TPM budget needs a hard output ceiling and low effort (same
# pin as breakdown — strict json_schema needs the gpt-oss line on Groq).
MAX_COMPLETION_TOKENS = 4096
REASONING_EFFORT = "low"

IMPORT_SYSTEM_PROMPT = (
    "You extract actionable tasks from freeform user notes.\n"
    "Rules:\n"
    f"- At most {MAX_PROPOSALS} proposals; one note may contain several tasks.\n"
    "- Extract ACTIONABLE items only — skip context, musings, and FYI lines.\n"
    "- Never invent tasks, dates, priorities, or projects the notes do not state.\n"
    "- Keep the user's own wording; titles are short imperatives.\n"
    "- proposed_deadline: resolve relative dates against today's date to an\n"
    "  absolute ISO 8601 datetime; null when the notes state no date.\n"
    "- priority: map explicit urgency/importance cues to LOW/MEDIUM/HIGH;\n"
    "  MEDIUM when unstated.\n"
    "- suggested_project_id: an id from the provided existing-projects list\n"
    "  when an item clearly belongs there; otherwise null. Never invent ids.\n"
    "- subtasks: concrete sub-steps only when the notes state them.\n"
    '- If the input contains no actionable items, return {"proposals": []}.\n'
)

IMPORT_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "import_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "proposals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": ["string", "null"]},
                            "proposed_deadline": {"type": ["string", "null"]},
                            "priority": {
                                "type": "string",
                                "enum": ["LOW", "MEDIUM", "HIGH"],
                            },
                            "suggested_project_id": {"type": ["integer", "null"]},
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
                        "required": [
                            "title",
                            "description",
                            "proposed_deadline",
                            "priority",
                            "suggested_project_id",
                            "subtasks",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["proposals"],
            "additionalProperties": False,
        },
    },
}


class ImportSubtaskProposal(BaseModel):
    """One proposed subtask row."""

    title: str


class ImportTaskProposal(BaseModel):
    """One proposed import card (title + extraction hints)."""

    title: str
    description: Optional[str] = None
    proposed_deadline: Optional[datetime] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    suggested_project_id: Optional[int] = None
    subtasks: list[ImportSubtaskProposal] = Field(default_factory=list)


class ImportExtraction(BaseModel):
    """Parse-degraded extraction returned to the client."""

    proposals: list[ImportTaskProposal] = Field(default_factory=list)
    reason: Optional[str] = None


def build_extract_prompt(
    text: str,
    today: date,
    projects: Sequence[tuple[int, str]] = (),
) -> str:
    """Serialize input text + today's UTC date + the user's existing projects."""
    clamped = text[:INPUT_CHAR_LIMIT]
    parts: list[str] = [f"Today's date (UTC): {today.isoformat()}"]
    if projects:
        rendered = "\n".join(f"- {project_id}: {name}" for project_id, name in projects)
        parts.append(f"Existing projects (use these ids only):\n{rendered}")
    parts.extend(["Input:", "<input>", clamped, "</input>"])
    return "\n\n".join(parts)


def _clean_title(value: Any) -> str:
    return str(value or "").strip()


def _parse_deadline(value: Any) -> Optional[datetime]:
    """ISO 8601 string -> datetime; unparseable/missing drops to None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_priority(value: Any) -> TaskPriority:
    try:
        return TaskPriority(str(value).upper())
    except ValueError:
        return TaskPriority.MEDIUM


def _parse_item(item: Any, valid_project_ids: Collection[int]) -> Optional[ImportTaskProposal]:
    """One raw proposal dict -> validated proposal; None when unusable."""
    if not isinstance(item, dict):
        return None
    title = _clean_title(item.get("title"))
    if not title:
        return None
    project_raw = item.get("suggested_project_id")
    try:
        project_id = int(project_raw) if project_raw is not None else None
    except (TypeError, ValueError):
        project_id = None
    if project_id not in valid_project_ids:
        project_id = None
    subtasks = [
        ImportSubtaskProposal(title=sub_title)
        for sub in item.get("subtasks") or []
        if isinstance(sub, dict) and (sub_title := _clean_title(sub.get("title")))
    ]
    return ImportTaskProposal(
        title=title,
        description=_clean_title(item.get("description")) or None,
        proposed_deadline=_parse_deadline(item.get("proposed_deadline")),
        priority=_parse_priority(item.get("priority")),
        suggested_project_id=project_id,
        subtasks=subtasks[:MAX_SUBTASKS_PER_PROPOSAL],
    )


def parse_proposals(answer_text: str, valid_project_ids: Collection[int]) -> ImportExtraction:
    """Strict-parse the model output; degrade to empty-with-reason, never raise.

    ``valid_project_ids`` scopes suggested_project_id to projects the user
    actually owns — anything else (hallucinated or foreign) drops to None.
    """
    try:
        raw = json.loads(answer_text)
        proposals_raw = raw["proposals"]
        if not isinstance(proposals_raw, list):
            raise ValueError("proposals is not a list")
    except Exception as exc:
        logger.warning("import extraction parse failure: %s", exc)
        return ImportExtraction(proposals=[], reason="extraction could not be generated")

    proposals: list[ImportTaskProposal] = []
    for item in proposals_raw:
        proposal = _parse_item(item, valid_project_ids)
        if proposal is not None:
            proposals.append(proposal)
        if len(proposals) >= MAX_PROPOSALS:
            break
    return ImportExtraction(proposals=proposals)


async def generate_extraction(
    prompt: str,
    valid_project_ids: Collection[int],
) -> tuple[ImportExtraction, LLMCallRecord, str]:
    """One structured-output call; returns (extraction, record, raw answer)."""
    start = time.monotonic()
    response = await asyncio.to_thread(
        assistant._call_completion,
        BREAKDOWN_MODEL,
        [
            {"role": "system", "content": IMPORT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        IMPORT_RESPONSE_FORMAT,
        MAX_COMPLETION_TOKENS,
        REASONING_EFFORT,
    )
    response_time = time.monotonic() - start

    answer_text = response.choices[0].message.content or ""
    usage = response.usage
    record = LLMCallRecord(
        model=BREAKDOWN_MODEL,
        prompt=prompt,
        instructions=IMPORT_SYSTEM_PROMPT,
        answer=answer_text,
        prompt_tokens=getattr(usage, "prompt_tokens", 0),
        completion_tokens=getattr(usage, "completion_tokens", 0),
        total_tokens=getattr(usage, "total_tokens", 0),
        response_time=response_time,
        cost=0.0,
    )
    return parse_proposals(answer_text, valid_project_ids), record, answer_text
