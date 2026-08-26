"""API endpoint for the voice assistant (POST /api/v1/voice/plan)."""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, TypeVar

import openai
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.knowledge import AI_NOT_CONFIGURED, AI_UNAVAILABLE
from app.config import (
    LLM_VOICE_RESERVE_TOKENS,
    RATE_LIMIT_VOICE,
    SYNTHETIC_CALENDAR_ENABLED,
    VOICE_ENABLED,
    WHISPER_MODEL,
)
from app.crud.voice import create_voice_answer
from app.dependencies import get_db
from app.knowledge.assistant import AssistantNotConfiguredError
from app.knowledge.budget import (
    BudgetExceededError,
    reconcile_llm_usage,
    refund_llm_reservation,
    reserve_llm_budget,
)
from app.knowledge.voice import MAX_AUDIO_BYTES, is_blank_transcript, transcribe_audio
from app.limiter import limiter
from app.models.user import User
from app.planner.connector import SyntheticCalendarConnector
from app.planner.service import create_plan
from app.schemas.plan import PlanResponse
from app.schemas.voice import VoicePlanResponse
from app.security import get_confirmed_user

ROUTER_TAG = "voice"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={401: {"description": "Not authenticated"}},
)

logger = logging.getLogger(__name__)

BLANK_TRANSCRIPT_DETAIL = "Couldn't hear anything — get a bit closer and try again."
AUDIO_TOO_LARGE_DETAIL = f"Audio too large ({MAX_AUDIO_BYTES // (1024 * 1024)} MB max)"

_T = TypeVar("_T")


async def _provider_call_or_503(
    step: str,
    user_id: int,
    call: Callable[[], Awaitable[_T]],
    on_provider_error: Callable[[], Awaitable[None]] | None = None,
) -> _T:
    """Run one provider call with the house error mapping.

    Missing key → AI_NOT_CONFIGURED; provider outage → AI_UNAVAILABLE.
    Callers snapshot user_id first (audit #27). When the caller has an
    outstanding budget reservation (ADR 0002), it passes
    ``on_provider_error`` — invoked before raising so the prepaid estimate is
    refunded on every abort-after-reservation path.
    """
    try:
        return await call()
    except AssistantNotConfiguredError as exc:
        logger.warning("voice %s not configured user=%s: %s", step, user_id, exc)
        if on_provider_error is not None:
            await on_provider_error()
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        logger.warning("voice %s unavailable user=%s: %s", step, user_id, exc)
        if on_provider_error is not None:
            await on_provider_error()
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc


async def _plan_or_503(db: AsyncSession, user_id: int) -> PlanResponse:
    """The existing stateless planner. Its embedding path raises bare
    ``RuntimeError`` when the provider key is missing — normalized here so the
    shared mapper sees one config-error type and stray RuntimeErrors still 500."""
    connector = SyntheticCalendarConnector() if SYNTHETIC_CALENDAR_ENABLED else None
    try:
        return await create_plan(db, user_id, None, None, connector)
    except RuntimeError as exc:
        raise AssistantNotConfiguredError(f"planner unavailable: {exc}") from exc


@router.post(
    "/voice/plan",
    response_model=VoicePlanResponse,
    responses={
        404: {"description": "Voice feature is disabled"},
        413: {"description": AUDIO_TOO_LARGE_DETAIL},
        422: {"description": BLANK_TRANSCRIPT_DETAIL},
        429: {"description": "Daily AI usage limit reached"},
        503: {"description": AI_UNAVAILABLE},
    },
)
@limiter.limit(RATE_LIMIT_VOICE)
async def voice_plan(
    request: Request,
    response: Response,
    audio: Annotated[UploadFile, File()],
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VoicePlanResponse:
    """Transcribe one recording and plan with it (stateless; pure trigger)."""
    if not VOICE_ENABLED:
        raise HTTPException(status_code=404, detail="Voice feature is disabled")

    # Snapshot the user id before the provider calls release the pooled
    # connection with a rollback that expires every ORM instance (audit #27).
    user_id = current_user.id
    logger.info("POST /voice/plan - %s", user_id)

    # Per-user daily spend cap (audit #29; ADR 0002): ONE reservation sized
    # for transcription + plan combined, committed atomically before any
    # provider call so concurrent requests can never oversubscribe the cap.
    # STT still bills in Groq's separate ASH/ASD buckets (invisible to the
    # instrumented totals), but the prepaid estimate covers its envelope.
    try:
        await reserve_llm_budget(db, user_id, LLM_VOICE_RESERVE_TOKENS)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Daily AI usage limit reached. Try again tomorrow.",
        ) from exc

    async def _refund() -> None:
        await refund_llm_reservation(db, user_id, LLM_VOICE_RESERVE_TOKENS)

    # Early exit before materializing the body; the capped read below stays as
    # belt-and-braces for clients that lie about Content-Length.
    if audio.size is not None and audio.size > MAX_AUDIO_BYTES:
        await refund_llm_reservation(db, user_id, LLM_VOICE_RESERVE_TOKENS)
        raise HTTPException(status_code=413, detail=AUDIO_TOO_LARGE_DETAIL)

    # Read at most one byte over the cap so an oversized body is never
    # fully materialized in memory.
    audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
    await audio.close()
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        await refund_llm_reservation(db, user_id, LLM_VOICE_RESERVE_TOKENS)
        raise HTTPException(status_code=413, detail=AUDIO_TOO_LARGE_DETAIL)

    # Release the pooled connection before the seconds-long provider calls
    # (audit #27 pattern, mirrors breakdown router). The reservation survives:
    # reserve_llm_budget commits its own short transaction by contract.
    await db.rollback()

    filename = audio.filename or "audio.webm"
    transcript, stt_latency = await _provider_call_or_503(
        "stt", user_id, lambda: transcribe_audio(audio_bytes, filename), on_provider_error=_refund
    )

    if is_blank_transcript(transcript):
        # Nothing instrumentable was spent on a blank transcript; refunding
        # keeps parity with pre-reservation semantics where blank exits
        # consumed no budget.
        await refund_llm_reservation(db, user_id, LLM_VOICE_RESERVE_TOKENS)
        raise HTTPException(status_code=422, detail=BLANK_TRANSCRIPT_DETAIL)

    # Route the planner through the shared mapper: it normalizes the planner's
    # bare RuntimeError into AssistantNotConfiguredError, and the mapper turns
    # both that and openai.APIError into 503 with a refund attached.
    plan = await _provider_call_or_503(
        "plan", user_id, lambda: _plan_or_503(db, user_id), on_provider_error=_refund
    )

    await create_voice_answer(
        db,
        user_id=user_id,
        transcript=transcript,
        audio_bytes=len(audio_bytes),
        stt_model=WHISPER_MODEL,
        stt_latency_s=stt_latency,
        plan=plan,
    )
    # Reconcile the reservation to the plan call's actual spend (flush-only;
    # STT tokens are untracked); the final commit below persists it.
    await reconcile_llm_usage(db, user_id, LLM_VOICE_RESERVE_TOKENS, plan.total_tokens)
    await db.commit()
    return VoicePlanResponse(transcript=transcript, plan=plan)
