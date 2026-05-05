from app.database import database, tbl_audit_log

async def log_action(user_id: int, action: str, target_type: str, target_id: int | None = None, details: str | None = None):
    """
    Log an action performed by a user on a specific target resource.
    """
    query = tbl_audit_log.insert().values(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details
    )
    await database.execute(query)
