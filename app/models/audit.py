from datetime import datetime
from pydantic import BaseModel

class AuditLog(BaseModel):
    id: int
    user_id: int
    action: str
    target_type: str
    target_id: int | None = None
    details: str | None = None
    created_at: datetime

class AuditLogCreate(BaseModel):
    action: str
    target_type: str
    target_id: int | None = None
    details: str | None = None
