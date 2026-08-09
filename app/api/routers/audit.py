"""API endpoints for retrieving audit logs."""

import logging
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_AUDIT_LIST
from app.crud import audit as audit_crud
from app.dependencies import get_db
from app.limiter import limiter
from app.models.audit import AuditLog as AuditLogModel
from app.models.user import User
from app.schemas.audit import AuditLog
from app.security import get_confirmed_user

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
    },
)

logger = logging.getLogger(__name__)


@router.get("/logs", response_model=list[AuditLog])
@limiter.limit(RATE_LIMIT_AUDIT_LIST)
async def list_audit_logs(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    task_id: Annotated[Optional[int], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: Annotated[Optional[str], Query()] = None,
    target_type: Annotated[Optional[str], Query()] = None,
    start_date: Annotated[Optional[datetime], Query()] = None,
    end_date: Annotated[Optional[datetime], Query()] = None,
) -> list[AuditLogModel]:
    """
    Retrieve audit logs for the current user.
    """
    return await audit_crud.get_audit_logs(
        db,
        user_id=current_user.id,
        task_id=task_id,
        limit=limit,
        offset=offset,
        action=action,
        target_type=target_type,
        start_date=start_date,
        end_date=end_date,
    )
