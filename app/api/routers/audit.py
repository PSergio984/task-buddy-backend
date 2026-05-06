from typing import Annotated
from fastapi import APIRouter, Depends, Query
from app.database import database, tbl_audit_log
from app.security import get_current_user
from app.models.audit import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("/logs", response_model=list[AuditLog])
async def get_audit_logs(
    current_user: Annotated[dict, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: Annotated[str | None, Query()] = None,
    target_type: Annotated[str | None, Query()] = None,
):
    """
    Retrieve audit logs for the current user.
    """
    query = tbl_audit_log.select().where(tbl_audit_log.c.user_id == current_user["id"])
    
    if action:
        query = query.where(tbl_audit_log.c.action == action)
    if target_type:
        query = query.where(tbl_audit_log.c.target_type == target_type)
        
    query = query.order_by(tbl_audit_log.c.created_at.desc()).limit(limit).offset(offset)
    return await database.fetch_all(query)
