from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import stats as stats_crud
from app.dependencies import get_db
from app.limiter import limiter
from app.models.user import User
from app.schemas.stats import SystemOverview
from app.security import get_current_user

router = APIRouter(
    prefix="/stats",
    tags=["stats"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
    },
)

@router.get("/overview", response_model=SystemOverview)
@limiter.limit("20/minute")
async def get_system_overview(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Retrieve a summary of tasks and tag distribution for the current user.
    """
    return await stats_crud.get_system_overview(db, user_id=current_user.id)
