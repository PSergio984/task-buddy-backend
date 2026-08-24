"""Voice API wire shapes (POST /api/v1/voice/plan)."""

from pydantic import BaseModel

from app.schemas.plan import PlanResponse


class VoicePlanResponse(BaseModel):
    """Nested contract: what was heard + the plan it triggered."""

    transcript: str
    plan: PlanResponse
