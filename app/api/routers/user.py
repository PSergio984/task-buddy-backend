import logging
import sqlite3
import sqlalchemy.exc

from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Form, Depends, Request, Body
from fastapi.security import OAuth2PasswordRequestForm
from app.models.user import (
    User,
    UserIn,
    UsernameUpdate,
    PasswordUpdate,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.security import (
    get_password_hash,
    verify_password,
    authenticate_user,
    create_access_token,
    create_confirm_token,
    create_reset_token,
    get_subject_for_token_type,
    get_current_user,
)
from app.database import database, tbl_user
from app import tasks
from app.limiter import limiter

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
async def register_user(user: UserIn, background_tasks: BackgroundTasks, request: Request):
    hashed_password = get_password_hash(user.password)
    query = tbl_user.insert().values(
        email=user.email, password=hashed_password, username=user.username
    )

    logger.debug("Attempting to register user with email: %s", user.email)
    try:
        user_id = await database.execute(query)
    except (sqlalchemy.exc.IntegrityError, sqlite3.IntegrityError) as e:
        logger.warning("Registration failed: email %s already registered", user.email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=EMAIL_ALREADY_REGISTERED,
        ) from e

    confirmation_token = create_confirm_token(user_id)

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
    background_tasks: BackgroundTasks, email: Annotated[str, Body(embed=True)], request: Request
):
    """Resend a confirmation email for an existing, unconfirmed user.

    The endpoint enqueues the confirmation email as a background task and returns
    a simple JSON response indicating the action.
    """
    query = tbl_user.select().where(tbl_user.c.email == email)
    user = await database.fetch_one(query)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user["confirmed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already confirmed"
        )

    confirmation_token = create_confirm_token(user["id"])
    # Use API path for confirmation link (relative) to avoid needing Request here.
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
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request):
    auth_user = await authenticate_user(form_data.username, form_data.password)
    access_token = create_access_token(auth_user["id"])
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/confirm/{token}")
async def confirm_email(token: str):
    subject = get_subject_for_token_type(token, expected_type="confirm")
    try:
        user_id = int(subject)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid confirmation token",
        )
    query = tbl_user.update().where(tbl_user.c.id == user_id).values(confirmed=True)
    rows_affected = await database.execute(query)
    if rows_affected == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return {"detail": "Email confirmed"}


@router.get("/me", response_model=User)
async def get_my_profile(current_user: Annotated[dict, Depends(get_current_user)]):
    """
    Retrieve the current user's profile information.
    """
    return current_user


@router.patch("/me/username")
async def update_username(
    username_data: UsernameUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
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
    query = tbl_user.select().where(tbl_user.c.username == new_username)
    existing_user = await database.fetch_one(query)
    if existing_user and existing_user["id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken"
        )

    update_query = (
        tbl_user.update().where(tbl_user.c.id == current_user["id"]).values(username=new_username)
    )
    await database.execute(update_query)

    return {"message": "Username updated successfully"}


@router.patch("/me/password")
async def update_password(
    password_data: PasswordUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Update the current user's password securely.
    Verifies the current password before updating to the new one.
    """
    if not verify_password(password_data.current_password, current_user["password"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect current password"
        )

    if len(password_data.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long",
        )

    hashed_password = get_password_hash(password_data.new_password)
    update_query = (
        tbl_user.update().where(tbl_user.c.id == current_user["id"]).values(password=hashed_password)
    )
    await database.execute(update_query)

    return {"message": "Password updated successfully"}


@router.post("/logout")
async def logout(current_user: Annotated[dict, Depends(get_current_user)]):
    """
    Logout the current user.
    Since the application uses stateless JWTs, the client is responsible for discarding the token.
    This endpoint verifies the token is valid and returns a success message.
    """
    return {"detail": "Successfully logged out. Please clear your token from client storage."}


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    request: ForgotPasswordRequest, background_tasks: BackgroundTasks, fastapi_request: Request
):
    """
    Initiate password reset flow by sending an email with a reset token.
    """
    query = tbl_user.select().where(tbl_user.c.email == request.email)
    user = await database.fetch_one(query)

    if not user:
        # To avoid email enumeration, we return success even if user not found
        return {"detail": "If an account exists with this email, a reset link has been sent."}

    reset_token = create_reset_token(user["id"])
    # In a real app, this would be a full URL to a frontend page
    reset_url = str(fastapi_request.url_for("reset_password_page", token=reset_token))

    background_tasks.add_task(
        tasks.send_password_reset_email,
        user["email"],
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
async def reset_password(request: ResetPasswordRequest, fastapi_request: Request):
    """
    Reset user password using a valid reset token.
    """
    subject = get_subject_for_token_type(request.token, expected_type="reset")
    try:
        user_id = int(subject)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token",
        )

    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long",
        )

    hashed_password = get_password_hash(request.new_password)
    update_query = (
        tbl_user.update().where(tbl_user.c.id == user_id).values(password=hashed_password)
    )
    rows_affected = await database.execute(update_query)

    if rows_affected == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return {"detail": "Password reset successfully"}
