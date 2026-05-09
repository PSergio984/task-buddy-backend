import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app import tasks
from app.crud import user as user_crud
from app.dependencies import get_db
from app.limiter import limiter
from app.models.user import User as UserORM
from app.schemas.user import (
    ForgotPasswordRequest,
    PasswordUpdate,
    ResetPasswordRequest,
    User,
    UserCreateRequest,
    UsernameUpdate,
)
from app.security import (
    authenticate_user,
    create_access_token,
    create_confirm_token,
    create_reset_token,
    get_current_user,
    get_password_hash,
    get_subject_for_token_type,
    verify_password,
)
from app.config import ACCESS_TOKEN_EXPIRE_MINUTES

logger = logging.getLogger(__name__)

# Constants to avoid duplicated literals and improve OpenAPI docs
ROUTER_TAG = "users"
REGISTER_PATH = "/register"
TOKEN_PATH = "/token"

EMAIL_ALREADY_REGISTERED = "Email already exists"
AUTH_CREDENTIALS_ERROR = "Could not validate credentials"

router = APIRouter(tags=[ROUTER_TAG])


@router.post(
    REGISTER_PATH, status_code=201, responses={400: {"description": EMAIL_ALREADY_REGISTERED}}
)
@limiter.limit("5/minute")
async def register_user(
    user: UserCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    logger.debug("Attempting to register user with email: %s", user.email)
    existing_user = await user_crud.get_user_by_email(db, user.email)
    if existing_user:
        logger.warning("Registration failed: email %s already registered", user.email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=EMAIL_ALREADY_REGISTERED,
        )

    hashed_password = get_password_hash(user.password)
    db_user = await user_crud.create_user(db, user_in=user, hashed_password=hashed_password)
    await db.commit()
    await db.refresh(db_user)

    confirmation_token = create_confirm_token(db_user.id)

    background_tasks.add_task(
        tasks.send_confirmation_email,
        user.email,
        confirmation_url=str(request.url_for("confirm_email", token=confirmation_token)),
        suppress_exceptions=True,
    )

    return {
        "detail": "User Created: User registered successfully. Please check your email to confirm."
    }


@router.post("/resend-confirmation")
@limiter.limit("5/minute")
async def resend_confirmation(
    background_tasks: BackgroundTasks,
    email: Annotated[str, Body(embed=True)],
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Resend a confirmation email for an existing, unconfirmed user."""
    user = await user_crud.get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already confirmed"
        )

    confirmation_token = create_confirm_token(user.id)
    confirmation_url = f"/api/v1/users/confirm/{confirmation_token}"
    background_tasks.add_task(
        tasks.send_confirmation_email,
        email,
        confirmation_url=confirmation_url,
        suppress_exceptions=True,
    )
    return {"detail": "Confirmation email requeued"}


@router.post(TOKEN_PATH, responses={401: {"description": AUTH_CREDENTIALS_ERROR}})
@limiter.limit("5/minute")
async def login(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    auth_user = await authenticate_user(db, form_data.username, form_data.password)
    # Commit any potential lazy migration (password re-hash)
    await db.commit()
    access_token = create_access_token(auth_user.id)
    
    # Set HttpOnly cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False, # Set to True in production (HTTPS)
        samesite="lax", # Strict might be too restrictive for cross-site if dev env differs
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": auth_user.id,
            "username": auth_user.username,
            "email": auth_user.email,
        },
    }


@router.get("/confirm/{token}")
async def confirm_email(token: str, db: Annotated[AsyncSession, Depends(get_db)]):
    subject = get_subject_for_token_type(token, expected_type="confirm")
    try:
        user_id = int(subject)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid confirmation token",
        ) from err

    user = await user_crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await user_crud.update_user_confirmation(db, db_user=user, confirmed=True)
    await db.commit()

    return {"detail": "Email confirmed"}


@router.get("/me", response_model=User)
async def get_my_profile(current_user: Annotated[UserORM, Depends(get_current_user)]):
    """
    Retrieve the current user's profile information.
    """
    return current_user


@router.patch("/me/username")
async def update_username(
    username_data: UsernameUpdate,
    current_user: Annotated[UserORM, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Update the current user's username.
    Checks for uniqueness and length.
    """
    new_username = username_data.username.strip()
    if not new_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username cannot be empty"
        )

    if len(new_username) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be at least 3 characters long",
        )

    # Check if username is already taken
    existing_user = await user_crud.get_user_by_username(db, new_username)
    if existing_user and existing_user.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken"
        )

    await user_crud.update_user(db, db_user=current_user, update_data={"username": new_username})
    await db.commit()

    return {"message": "Username updated successfully"}


@router.patch("/me/password")
async def update_password(
    password_data: PasswordUpdate,
    current_user: Annotated[UserORM, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Update the current user's password securely.
    Verifies the current password before updating to the new one.
    """
    if not verify_password(password_data.current_password, current_user.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect current password"
        )

    if len(password_data.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long",
        )

    hashed_password = get_password_hash(password_data.new_password)
    await user_crud.update_user(db, db_user=current_user, update_data={"password": hashed_password})
    await db.commit()

    return {"message": "Password updated successfully"}


@router.post("/logout")
async def logout(
    response: Response,
    current_user: Annotated[UserORM, Depends(get_current_user)]
):
    """
    Logout the current user.
    """
    response.delete_cookie(key="access_token", path="/")
    return {"detail": "Successfully logged out."}


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    fastapi_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Initiate password reset flow by sending an email with a reset token.
    """
    user = await user_crud.get_user_by_email(db, request.email)

    if not user:
        # To avoid email enumeration, we return success even if user not found
        return {"detail": "If an account exists with this email, a reset link has been sent."}

    reset_token = create_reset_token(user.id)
    reset_url = str(fastapi_request.url_for("reset_password_page", token=reset_token))

    background_tasks.add_task(
        tasks.send_password_reset_email,
        user.email,
        reset_url=reset_url,
        suppress_exceptions=True,
    )

    return {"detail": "If an account exists with this email, a reset link has been sent."}


@router.get("/reset-password/{token}", include_in_schema=False)
async def reset_password_page(token: str):
    """
    Placeholder for the reset password page.
    In a real app, this would be handled by the frontend.
    """
    return {"detail": f"This is a placeholder for the reset password page with token: {token}"}


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: ResetPasswordRequest,
    fastapi_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Reset user password using a valid reset token.
    """
    subject = get_subject_for_token_type(request.token, expected_type="reset")
    try:
        user_id = int(subject)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token",
        ) from err

    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long",
        )

    user = await user_crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    hashed_password = get_password_hash(request.new_password)
    await user_crud.update_user(db, db_user=user, update_data={"password": hashed_password})
    await db.commit()

    return {"detail": "Password reset successfully"}
