import logging

from fastapi import APIRouter, HTTPException, status
from app.models.user import UserIn
from app.security import get_user, get_password_hash
from app.database import database, tbl_user


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/register", status_code=201)
async def register_user(user: UserIn):
    if await get_user(user.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    hashed_password = get_password_hash(user.password)
    query = tbl_user.insert().values(
        email=user.email, password=hashed_password, username=user.username
    )

    logger.debug(query)

    await database.execute(query)
