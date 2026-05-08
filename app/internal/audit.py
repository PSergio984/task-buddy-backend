from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.audit import create_audit_log
from app.schemas.enums import AuditAction


async def log_action(
    db: AsyncSession,
    user_id: int,
    action: str | AuditAction,
    target_type: str,
    target_id: int | None = None,
    details: str | None = None,
):
    """
    Log an action performed by a user on a specific target resource.
    """
    await create_audit_log(
        db=db,
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
