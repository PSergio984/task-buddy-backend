from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import audit as audit_crud
from app.dependencies import get_db
from app.limiter import limiter
from app.models.user import User
from app.schemas.audit import AuditLog as AuditLogSchema
from app.security import get_current_user

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
    },
)

@router.get("/logs", response_model=list[AuditLogSchema])
@limiter.limit("20/minute")
async def get_audit_logs(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: Annotated[str | None, Query()] = None,
    target_type: Annotated[str | None, Query()] = None,
):
    """
    Retrieve audit logs for the current user.
    """
    return await audit_crud.get_audit_logs(
        db,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        action=action,
        target_type=target_type
    )
