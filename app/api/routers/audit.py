from typing import Annotated, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db
from app.security import get_current_user
from app.models.user import User
from app.models.audit import AuditLog as AuditLogORM
from app.schemas.audit import AuditLog as AuditLogSchema
from app.crud import audit as audit_crud

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("/logs", response_model=List[AuditLogSchema])
async def get_audit_logs(
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
