"""API endpoints for task-attached knowledge (notes)."""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Annotated, Any, Optional

import anyio
import openai
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.task import invalidate_task_cache
from app.config import (
    KNOWLEDGE_STREAM_ENABLED,
    LLM_ASK_RESERVE_TOKENS,
    RATE_LIMIT_KNOWLEDGE_ASK,
    RATE_LIMIT_KNOWLEDGE_CREATE,
    RATE_LIMIT_KNOWLEDGE_DELETE,
    RATE_LIMIT_KNOWLEDGE_FEEDBACK,
    RATE_LIMIT_KNOWLEDGE_LIST,
    RATE_LIMIT_KNOWLEDGE_UPDATE,
)
from app.crud import knowledge as knowledge_crud
from app.crud import task as task_crud
from app.dependencies import get_db
from app.knowledge.assistant import (
    AskStreamContext,
    AssistantNotConfiguredError,
    KnowledgeAssistant,
)
from app.knowledge.budget import (
    BudgetExceededError,
    reconcile_llm_usage,
    refund_llm_reservation,
    reserve_llm_budget,
)
from app.knowledge.ingest import ingest_knowledge
from app.knowledge.retrieval import UserKnowledgeIndex
from app.limiter import limiter
from app.models.knowledge import KnowledgeFeedback, SourceType, TaskKnowledge
from app.models.user import User
from app.schemas.knowledge import (
    Citation,
    FeedbackCreateRequest,
    FeedbackResponse,
    KnowledgeAskRequest,
    KnowledgeAskResponse,
    KnowledgeCreateRequest,
    KnowledgeResponse,
    KnowledgeUpdateRequest,
)
from app.security import get_confirmed_user

# Constants to avoid duplicated string literals
ROUTER_TAG = "knowledge"
TASK_NOT_FOUND = "Task not found"
KNOWLEDGE_NOT_FOUND = "Knowledge not found"
ANSWER_NOT_FOUND = "Answer not found"
NO_FIELDS_TO_UPDATE = "No fields to update"
AI_NOT_CONFIGURED = "AI assistant not configured"
AI_UNAVAILABLE = "AI assistant unavailable"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={
        404: {"description": TASK_NOT_FOUND},
        401: {"description": "Not authenticated"},
    },
)

logger = logging.getLogger(__name__)


@router.post(
    "/{task_id}/knowledge",
    response_model=KnowledgeResponse,
    status_code=201,
    responses={
        404: {"description": TASK_NOT_FOUND},
        400: {"description": "Bad request"},
    },
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_CREATE)
async def create_knowledge(
    task_id: int,
    knowledge_in: KnowledgeCreateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskKnowledge:
    logger.info("POST /tasks/%s/knowledge - %s", task_id, current_user.id)

    if knowledge_in.source_type != SourceType.NOTE:
        raise HTTPException(
            status_code=400, detail="Only the note source type is supported for now"
        )

    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    db_knowledge: TaskKnowledge = await knowledge_crud.create_knowledge(
        db, task_id=task_id, user_id=current_user.id, knowledge_in=knowledge_in
    )
    await db.commit()
    await db.refresh(db_knowledge)

    # Index the note for retrieval (chunks persisted in a second transaction).
    # Ingest failure degrades search only — the note itself stays saved.
    try:
        await ingest_knowledge(db, db_knowledge)
        await db.commit()
        await UserKnowledgeIndex().ensure_index(db, current_user.id)
    except Exception as exc:
        await db.rollback()
        logger.warning("knowledge ingest failed for id=%s: %s", db_knowledge.id, exc)

    logger.info("POST /tasks/%s/knowledge - created id=%s", task_id, db_knowledge.id)
    await invalidate_task_cache(current_user.id, task_id)
    return db_knowledge


@router.get(
    "/{task_id}/knowledge",
    response_model=list[KnowledgeResponse],
    responses={404: {"description": TASK_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_LIST)
async def list_knowledge(
    task_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TaskKnowledge]:
    logger.info("GET /tasks/%s/knowledge - %s", task_id, current_user.id)

    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    return await knowledge_crud.list_knowledge_for_task(
        db, task_id=task_id, user_id=current_user.id, skip=offset, limit=limit
    )


@router.get(
    "/{task_id}/knowledge/{knowledge_id}",
    response_model=KnowledgeResponse,
    responses={404: {"description": KNOWLEDGE_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_LIST)
async def get_knowledge(
    task_id: int,
    knowledge_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskKnowledge:
    logger.info("GET /tasks/%s/knowledge/%s - %s", task_id, knowledge_id, current_user.id)

    db_knowledge = await knowledge_crud.get_knowledge(
        db, knowledge_id=knowledge_id, user_id=current_user.id
    )
    if not db_knowledge or db_knowledge.task_id != task_id:
        raise HTTPException(status_code=404, detail=KNOWLEDGE_NOT_FOUND)

    return db_knowledge


@router.put(
    "/{task_id}/knowledge/{knowledge_id}",
    response_model=KnowledgeResponse,
    responses={
        404: {"description": KNOWLEDGE_NOT_FOUND},
        400: {"description": "Bad request"},
    },
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_UPDATE)
async def update_knowledge(
    task_id: int,
    knowledge_id: int,
    knowledge_update: KnowledgeUpdateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskKnowledge:
    logger.info("PUT /tasks/%s/knowledge/%s - %s", task_id, knowledge_id, current_user.id)

    update_data = knowledge_update.model_dump(exclude_unset=True)
    if not update_data:
        logger.warning("PUT /tasks/%s/knowledge/%s - no fields to update", task_id, knowledge_id)
        raise HTTPException(status_code=400, detail=NO_FIELDS_TO_UPDATE)

    db_knowledge: TaskKnowledge | None = await knowledge_crud.update_knowledge(
        db, knowledge_id=knowledge_id, user_id=current_user.id, knowledge_in=knowledge_update
    )
    if not db_knowledge or db_knowledge.task_id != task_id:
        raise HTTPException(status_code=404, detail=KNOWLEDGE_NOT_FOUND)

    await db.commit()
    await db.refresh(db_knowledge)

    # Re-index: drop the old chunks, embed the updated content.
    # Failure degrades search only — the content edit itself stays saved.
    try:
        await UserKnowledgeIndex().remove_knowledge_chunks(
            db, user_id=current_user.id, knowledge_id=db_knowledge.id
        )
        await ingest_knowledge(db, db_knowledge)
        await db.commit()
        await UserKnowledgeIndex().ensure_index(db, current_user.id)
    except Exception as exc:
        await db.rollback()
        logger.warning("knowledge re-ingest failed for id=%s: %s", db_knowledge.id, exc)

    logger.info("PUT /tasks/%s/knowledge/%s - updated", task_id, knowledge_id)
    await invalidate_task_cache(current_user.id, task_id)
    return db_knowledge


@router.delete(
    "/{task_id}/knowledge/{knowledge_id}",
    status_code=204,
    responses={404: {"description": KNOWLEDGE_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_DELETE)
async def delete_knowledge(
    task_id: int,
    knowledge_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    logger.info("DELETE /tasks/%s/knowledge/%s - %s", task_id, knowledge_id, current_user.id)

    db_knowledge = await knowledge_crud.get_knowledge(
        db, knowledge_id=knowledge_id, user_id=current_user.id
    )
    if not db_knowledge or db_knowledge.task_id != task_id:
        raise HTTPException(status_code=404, detail=KNOWLEDGE_NOT_FOUND)

    deleted = await knowledge_crud.delete_knowledge(
        db, knowledge_id=knowledge_id, user_id=current_user.id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail=KNOWLEDGE_NOT_FOUND)

    await UserKnowledgeIndex().remove_knowledge_chunks(
        db, user_id=current_user.id, knowledge_id=knowledge_id
    )
    await db.commit()
    try:
        # Drop the deleted chunks from the in-memory index. A rebuild failure
        # must not 5xx an already-committed deletion.
        await UserKnowledgeIndex().ensure_index(db, current_user.id)
    except Exception as exc:
        logger.warning("knowledge index rebuild failed after delete id=%s: %s", knowledge_id, exc)

    logger.info("DELETE /tasks/%s/knowledge/%s - deleted", task_id, knowledge_id)
    await invalidate_task_cache(current_user.id, task_id)
    response.status_code = 204
    return response


@router.post(
    "/{task_id}/knowledge/ask",
    response_model=KnowledgeAskResponse,
    responses={
        404: {"description": TASK_NOT_FOUND},
        503: {"description": AI_NOT_CONFIGURED},
    },
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_ASK)
async def ask_knowledge(
    task_id: int,
    ask_in: KnowledgeAskRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeAskResponse:
    """Answer 'what do I need for this task' from the task's knowledge.

    Ownership runs BEFORE any LLM call (T-7-14: a foreign task 404s with zero
    spend). The OpenAI key check lives in ``_openai_client``; a missing key
    surfaces as a generic 503 (no key-presence leak, T-7-13).
    """
    logger.info("POST /tasks/%s/knowledge/ask - %s", task_id, current_user.id)

    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    # Snapshot the user id BEFORE the reservation and any provider call: the
    # assistant rolls back mid-request (audit #27), which expires every ORM
    # instance — touching current_user.id afterwards would lazy-load outside a
    # greenlet context (MissingGreenlet). Same discipline as plan/breakdown.
    user_id = current_user.id

    # Per-user daily spend cap (audit #29; ADR 0002): reserved atomically via
    # a conditional UPDATE that commits before any provider call, so
    # concurrent requests can never oversubscribe the cap. The foreign-task
    # 404 above stays BEFORE this reservation so zero-spend-on-404 holds.
    try:
        await reserve_llm_budget(db, user_id, LLM_ASK_RESERVE_TOKENS)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Daily AI usage limit reached. Try again tomorrow.",
        ) from exc

    assistant = KnowledgeAssistant()
    try:
        answer_row = await assistant.ask(db, db_task, ask_in.query)
    except AssistantNotConfiguredError as exc:
        logger.warning("knowledge ask not configured for task=%s: %s", task_id, exc)
        await refund_llm_reservation(db, user_id, LLM_ASK_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        # Key set but the provider failed (401/429/network) — still a 503,
        # never a 500; no provider internals leak into the response.
        logger.warning(
            "knowledge ask unavailable for task=%s: %s (cause: %r)",
            task_id,
            exc,
            exc.__cause__,
        )
        await refund_llm_reservation(db, user_id, LLM_ASK_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc
    except RuntimeError as exc:
        # Embedding path raises RuntimeError when the OpenAI key is missing
        # (config-level); surface the same 503 as the completion path.
        logger.warning("knowledge ask not configured (embeddings) task=%s: %s", task_id, exc)
        await refund_llm_reservation(db, user_id, LLM_ASK_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc

    # Reconcile the reservation to actual spend (flush-only); the final
    # commit below persists it.
    await reconcile_llm_usage(db, user_id, LLM_ASK_RESERVE_TOKENS, answer_row.total_tokens)
    await db.commit()
    await db.refresh(answer_row)

    citations = [Citation.model_validate(chunk) for chunk in (answer_row.retrieved_chunks or [])]
    logger.info(
        "POST /tasks/%s/knowledge/ask - answered id=%s model=%s",
        task_id,
        answer_row.id,
        answer_row.model,
    )
    return KnowledgeAskResponse(
        task_id=task_id,
        answer=answer_row.answer,
        citations=citations,
        model=answer_row.model,
        prompt_tokens=answer_row.prompt_tokens,
        completion_tokens=answer_row.completion_tokens,
        total_tokens=answer_row.total_tokens,
        cost_usd=float(answer_row.cost_usd or 0),
        response_time_ms=answer_row.response_time_ms,
        judge_verdict=answer_row.judge_verdict.value if answer_row.judge_verdict else None,
        judge_explanation=answer_row.judge_explanation,
        answer_id=answer_row.id,
    )


def _sse_frame(event: str, payload: dict) -> str:
    """One SSE frame: ``event:`` name plus a JSON ``data:`` payload."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _sse_event_frame(event: dict) -> Optional[str]:
    """Map one streamed internal event to an SSE frame; internal-only kinds
    (``record``, ``answer``) return None and are handled by the endpoint."""
    kind = event["event"]
    if kind == "citations":
        return _sse_frame("citations", {"citations": event["citations"]})
    if kind == "token":
        return _sse_frame("token", {"text": event["text"]})
    if kind == "verdict":
        return _sse_frame(
            "verdict",
            {"relevance": event["relevance"], "explanation": event["explanation"]},
        )
    return None


async def _done_frame(
    db: AsyncSession,
    answer_row: Any,
    usage_reported: bool,
    user_id: int,
    task_id: int,
) -> str:
    """Reconcile the reservation to actual spend, commit, then emit ``done``.

    A provider that omits the usage chunk reconciles at the reserved amount
    (conservative, never under-bills).
    """
    actual = answer_row.total_tokens if usage_reported else LLM_ASK_RESERVE_TOKENS
    await reconcile_llm_usage(db, user_id, LLM_ASK_RESERVE_TOKENS, actual)
    await db.commit()
    return _sse_frame(
        "done",
        {
            "answer_id": answer_row.id,
            "task_id": task_id,
            "model": answer_row.model,
            "prompt_tokens": answer_row.prompt_tokens,
            "completion_tokens": answer_row.completion_tokens,
            "total_tokens": answer_row.total_tokens,
            "cost_usd": float(answer_row.cost_usd or 0),
            "response_time_ms": float(answer_row.response_time_ms or 0),
            # Explicit marker: False means the token fields are unmeasured
            # zeros and the reservation was charged, not "free usage".
            "usage_reported": usage_reported,
        },
    )


async def _refund_reservation(db: AsyncSession, user_id: int, task_id: int) -> bool:
    """Roll back pending ORM state, refund the prepaid estimate, report success.

    The rollback matters when the failure landed after ``create_answer``'s
    flush — otherwise the refund's own commit would persist an orphan row.
    """
    try:
        await db.rollback()
        await refund_llm_reservation(db, user_id, LLM_ASK_RESERVE_TOKENS)
        return True
    except Exception:
        logger.exception("stream refund failed for task=%s", task_id)
        return False


async def _settle_reservation(db: AsyncSession, user_id: int, task_id: int, actual: int) -> None:
    """Charge the reservation on abort paths where generation was consumed.

    A disconnect is not a provider failure: the work happened, so settle the
    way ``/ask`` does (actual when reported, else the reserve). Refunding here
    would let a client read the full answer, hang up, and keep the tokens.
    """
    try:
        await db.rollback()
        await reconcile_llm_usage(db, user_id, LLM_ASK_RESERVE_TOKENS, actual)
        await db.commit()
    except Exception:
        logger.exception("stream settlement failed for task=%s", task_id)


async def _knowledge_sse_stream(
    assistant: KnowledgeAssistant,
    db: AsyncSession,
    stream_ctx: AskStreamContext,
    user_id: int,
    task_id: int,
) -> AsyncGenerator[str, None]:
    """Map ask_stream events to SSE frames; reconcile/refund the reservation."""
    usage_reported = True
    # Tokens actually generated, when the provider reports them — used to
    # settle at real spend if the client disconnects mid-flight.
    stream_tokens = LLM_ASK_RESERVE_TOKENS
    # Every abort-after-reservation path must settle the prepaid estimate —
    # including client disconnects, which surface as GeneratorExit and skip
    # the except clauses entirely (ADR 0002). stream_ctx.generation_started is
    # the refund boundary: before the provider request is sent a disconnect
    # consumed nothing billable (refund); from then on it settles like /ask.
    settled = False
    try:
        async for event in assistant.ask_stream(db, stream_ctx):
            kind = event["event"]
            if kind == "record":
                usage_reported = event["usage_reported"]
                stream_tokens = event["record"].total_tokens
            elif kind == "answer":
                frame = await _done_frame(db, event["answer"], usage_reported, user_id, task_id)
                # Settled once reconcile+commit land — before the done frame is
                # yielded, so a disconnect at this exact yield can't over-refund.
                settled = True
                yield frame
            else:
                event_frame = _sse_event_frame(event)
                if event_frame is not None:
                    yield event_frame
    except openai.APIError as exc:
        # Status line is already sent; a provider failure mid-stream surfaces
        # as a terminal error event, then the stream closes.
        logger.warning("knowledge ask stream provider error for task=%s: %s", task_id, exc)
        settled = await _refund_reservation(db, user_id, task_id)
        yield _sse_frame("error", {"code": "provider_error", "message": "AI service unavailable"})
    except Exception:
        # Any other mid-stream failure (judge, citations, reconcile) — still
        # close with a terminal error frame rather than an abrupt abort.
        logger.exception("knowledge ask stream failed for task=%s", task_id)
        settled = await _refund_reservation(db, user_id, task_id)
        yield _sse_frame("error", {"code": "internal_error", "message": "AI service unavailable"})
    finally:
        if not settled:
            # Shielded: a disconnect mid-await re-raises Cancelled at every
            # checkpoint, which would kill the settlement exactly when it is
            # needed most.
            with anyio.CancelScope(shield=True):
                if stream_ctx.generation_started:
                    await _settle_reservation(
                        db,
                        user_id,
                        task_id,
                        stream_tokens if usage_reported else LLM_ASK_RESERVE_TOKENS,
                    )
                else:
                    await _refund_reservation(db, user_id, task_id)


@router.post(
    "/{task_id}/knowledge/ask/stream",
    responses={
        404: {"description": "Task not found or streaming disabled"},
        503: {"description": AI_NOT_CONFIGURED},
    },
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_ASK)
async def ask_knowledge_stream(
    task_id: int,
    ask_in: KnowledgeAskRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """SSE variant of /ask: citations -> token deltas -> verdict -> done.

    Pre-stream failures stay normal HTTP errors (the status line is sent once
    streaming begins); a mid-stream provider failure downgrades to a terminal
    ``error`` SSE event instead (docs/specs/knowledge-ask-streaming.md).
    """
    if not KNOWLEDGE_STREAM_ENABLED:
        raise HTTPException(status_code=404, detail="Knowledge streaming is disabled")

    logger.info("POST /tasks/%s/knowledge/ask/stream - %s", task_id, current_user.id)

    db_task = await task_crud.get_task(db, task_id=task_id, user_id=current_user.id)
    if not db_task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND)

    # Same snapshot discipline as /ask: mid-request rollbacks expire every
    # ORM instance (audit #27).
    user_id = current_user.id

    # Same ADR 0002 reservation as /ask, still AFTER the zero-spend 404.
    try:
        await reserve_llm_budget(db, user_id, LLM_ASK_RESERVE_TOKENS)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Daily AI usage limit reached. Try again tomorrow.",
        ) from exc

    assistant = KnowledgeAssistant()
    try:
        stream_ctx = await assistant.prepare_ask_stream(db, db_task, ask_in.query)
    except AssistantNotConfiguredError as exc:
        logger.warning("knowledge ask stream not configured for task=%s: %s", task_id, exc)
        await refund_llm_reservation(db, user_id, LLM_ASK_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        # Same mapping as /ask: provider failure pre-stream is still a 503.
        logger.warning("knowledge ask stream unavailable for task=%s: %s", task_id, exc)
        await refund_llm_reservation(db, user_id, LLM_ASK_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc
    except RuntimeError as exc:
        logger.warning("knowledge ask stream not configured (embeddings) task=%s: %s", task_id, exc)
        await refund_llm_reservation(db, user_id, LLM_ASK_RESERVE_TOKENS)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except Exception:
        # Anything unexpected (DB, retrieval) still owes a refund — the
        # reservation must not charge for a request that never streamed.
        logger.exception("knowledge ask stream preparation failed for task=%s", task_id)
        await refund_llm_reservation(db, user_id, LLM_ASK_RESERVE_TOKENS)
        raise

    return StreamingResponse(
        _knowledge_sse_stream(assistant, db, stream_ctx, user_id, task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/{task_id}/knowledge/answers/{answer_id}/feedback",
    response_model=FeedbackResponse,
    status_code=201,
    responses={404: {"description": ANSWER_NOT_FOUND}},
)
@limiter.limit(RATE_LIMIT_KNOWLEDGE_FEEDBACK)
async def create_answer_feedback(
    task_id: int,
    answer_id: int,
    feedback_in: FeedbackCreateRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeFeedback:
    """Record user +1/-1 feedback on an answer (owner-only, T-7-15/T-7-16)."""
    logger.info(
        "POST /tasks/%s/knowledge/answers/%s/feedback - %s",
        task_id,
        answer_id,
        current_user.id,
    )

    db_answer = await knowledge_crud.get_answer(db, answer_id=answer_id, user_id=current_user.id)
    if not db_answer or db_answer.task_id != task_id:
        raise HTTPException(status_code=404, detail=ANSWER_NOT_FOUND)

    feedback_row = await knowledge_crud.create_feedback(
        db,
        user_id=current_user.id,
        answer_id=answer_id,
        rating=feedback_in.rating,
        comment=feedback_in.comment,
    )
    await db.commit()
    await db.refresh(feedback_row)
    return feedback_row
