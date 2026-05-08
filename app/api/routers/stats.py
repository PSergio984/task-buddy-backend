from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db
from app.security import get_current_user
from app.models.user import User
from app.schemas.stats import SystemOverview
from app.crud import stats as stats_crud

router = APIRouter(prefix="/stats", tags=["stats"])

@router.get("/overview", response_model=SystemOverview)
async def get_system_overview(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Retrieve a summary of tasks and tag distribution for the current user.
    """
    return await stats_crud.get_system_overview(db, user_id=current_user.id)
