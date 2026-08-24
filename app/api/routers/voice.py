"""API endpoint for the voice assistant (POST /api/v1/voice/plan)."""

import logging
from typing import Annotated

import openai
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.knowledge import AI_NOT_CONFIGURED, AI_UNAVAILABLE
from app.config import RATE_LIMIT_VOICE, SYNTHETIC_CALENDAR_ENABLED, VOICE_ENABLED, WHISPER_MODEL
from app.crud.voice import create_voice_answer
from app.dependencies import get_db
from app.knowledge.assistant import AssistantNotConfiguredError
from app.knowledge.budget import BudgetExceededError, check_llm_budget
from app.knowledge.voice import MAX_AUDIO_BYTES, is_blank_transcript, transcribe_audio
from app.limiter import limiter
from app.models.user import User
from app.planner.connector import SyntheticCalendarConnector
from app.planner.service import create_plan
from app.schemas.voice import VoicePlanResponse
from app.security import get_confirmed_user

ROUTER_TAG = "voice"

router = APIRouter(
    tags=[ROUTER_TAG],
    responses={401: {"description": "Not authenticated"}},
)

logger = logging.getLogger(__name__)

BLANK_TRANSCRIPT_DETAIL = "Couldn't hear anything — get a bit closer and try again."


@router.post(
    "/voice/plan",
    response_model=VoicePlanResponse,
    responses={
        404: {"description": "Voice feature is disabled"},
        413: {"description": "Audio exceeds the 5 MB limit"},
        422: {"description": BLANK_TRANSCRIPT_DETAIL},
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

    # Per-user daily spend cap — checked before any provider call (audit #29).
    # It bounds the plan call's chat tokens only: STT bills in Groq's separate
    # ASH/ASD buckets and is invisible to check_llm_budget.
    try:
        await check_llm_budget(db, user_id)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="Daily AI usage limit reached. Try again tomorrow.",
        ) from exc

    audio_bytes = await audio.read()
    await audio.close()
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio too large (5 MB max)")

    # Release the pooled connection before the seconds-long provider calls
    # (audit #27 pattern, mirrors breakdown router).
    await db.rollback()

    try:
        transcript, stt_latency = await transcribe_audio(
            audio_bytes, audio.filename or "audio.webm"
        )
    except AssistantNotConfiguredError as exc:
        logger.warning("voice stt not configured for user=%s: %s", user_id, exc)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        logger.warning("voice stt unavailable for user=%s: %s", user_id, exc)
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc

    if is_blank_transcript(transcript):
        raise HTTPException(status_code=422, detail=BLANK_TRANSCRIPT_DETAIL)

    connector = SyntheticCalendarConnector() if SYNTHETIC_CALENDAR_ENABLED else None
    try:
        plan = await create_plan(db, user_id, None, None, connector)
    except AssistantNotConfiguredError as exc:
        logger.warning("voice plan not configured for user=%s: %s", user_id, exc)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc
    except openai.APIError as exc:
        logger.warning("voice plan unavailable for user=%s: %s", user_id, exc)
        raise HTTPException(status_code=503, detail=AI_UNAVAILABLE) from exc
    except RuntimeError as exc:
        # Embedding path raises RuntimeError when its provider key is missing.
        logger.warning("voice plan not configured (embeddings) user=%s: %s", user_id, exc)
        raise HTTPException(status_code=503, detail=AI_NOT_CONFIGURED) from exc

    await create_voice_answer(
        db,
        user_id=user_id,
        transcript=transcript,
        audio_bytes=len(audio_bytes),
        stt_model=WHISPER_MODEL,
        stt_latency_s=stt_latency,
        plan=plan,
    )
    await db.commit()
    return VoicePlanResponse(transcript=transcript, plan=plan)
