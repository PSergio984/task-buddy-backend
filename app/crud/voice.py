"""CRUD operations for voice instrumentation rows."""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice import VoiceAnswer
from app.schemas.plan import PlanResponse


async def create_voice_answer(
    db: AsyncSession,
    *,
    user_id: int,
    transcript: str,
    audio_bytes: int,
    stt_model: str,
    stt_latency_s: float,
    plan: PlanResponse,
) -> VoiceAnswer:
    """Persist one voice-instrumentation row (flush-not-commit; router commits).

    LLM metrics are mirrored verbatim from the triggered plan response, so a
    short-circuit lands as ``llm_model="rule"`` with zeroed tokens.
    """
    db_answer = VoiceAnswer(
        user_id=user_id,
        transcript=transcript,
        audio_bytes=audio_bytes,
        stt_model=stt_model,
        stt_latency_ms=round(stt_latency_s * 1000, 2),
        llm_model=plan.model,
        prompt_tokens=plan.prompt_tokens,
        completion_tokens=plan.completion_tokens,
        total_tokens=plan.total_tokens,
        cost_usd=Decimal(str(plan.cost_usd)),
        response_time_ms=plan.response_time_ms,
        available_minutes=plan.available_minutes,
    )
    db.add(db_answer)
    await db.flush()
    await db.refresh(db_answer)
    return db_answer
