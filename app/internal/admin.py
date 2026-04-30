"""
Admin module.

Contains admin-only functionality and operations.
Not exposed in the main API routes by default.
"""

from fastapi import APIRouter

router = APIRouter()


@router.post("/")
async def update_admin():
    """Admin update endpoint."""
    return {"message": "Admin operation completed"}
