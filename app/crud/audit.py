from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.schemas.enums import AuditAction


async def create_audit_log(
    db: AsyncSession,
    user_id: int,
    action: AuditAction | str,
    target_type: str,
    target_id: Optional[int] = None,
    details: Optional[str] = None,
) -> AuditLog:
    db_log = AuditLog(
        user_id=user_id,
        action=action.value if hasattr(action, 'value') else action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
    db.add(db_log)
    await db.flush()
    return db_log


async def get_audit_logs(
    db: AsyncSession,
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
) -> list[AuditLog]:
    from sqlalchemy import select
    query = select(AuditLog).where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)

    query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())
