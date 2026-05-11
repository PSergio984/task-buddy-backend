import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

import httpx
from sqlalchemy import update

from app.celery_app import celery_app
from app.config import config
from app.database import AsyncSessionLocal
from app.models.user import User

logger = logging.getLogger(__name__)


class APIResponseError(Exception):
    pass


def _is_valid_url(url: str | None) -> bool:
    """Helper to validate that a URL starts with https://."""
    return bool(url and url.startswith("https://"))


async def send_brevo_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> httpx.Response:
    mail_url = config.MAIL_URL
    if not _is_valid_url(mail_url):
        raise APIResponseError(
            f"Invalid MAIL_URL: {mail_url}. Must start with https://"
        )
    # Assert for type checker narrowing (mail_url is now guaranteed to be str)
    assert mail_url is not None

    if not config.MAIL_API_KEY:
        raise APIResponseError("Missing MAIL_API_KEY for Brevo transactional email")
    if not config.MAIL_FROM_EMAIL:
        raise APIResponseError("Missing MAIL_FROM_EMAIL for Brevo transactional email")

    payload = {
        "sender": {"email": config.MAIL_FROM_EMAIL, "name": config.MAIL_FROM_NAME},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text_body,
    }
    if html_body:
        payload["htmlContent"] = html_body

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            mail_url,
            headers={
                "api-key": config.MAIL_API_KEY,
                "accept": "application/json",
                "content-type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response


def send_smtp_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    if not config.MAIL_SMTP_HOST:
        raise APIResponseError("Missing MAIL_SMTP_HOST for Brevo SMTP transactional email")
    if not config.MAIL_SMTP_USERNAME:
        raise APIResponseError("Missing MAIL_SMTP_USERNAME for Brevo SMTP transactional email")
    if not config.MAIL_SMTP_PASSWORD:
        raise APIResponseError("Missing MAIL_SMTP_PASSWORD for Brevo SMTP transactional email")
    if not config.MAIL_FROM_EMAIL:
        raise APIResponseError("Missing MAIL_FROM_EMAIL for Brevo SMTP transactional email")

    message = EmailMessage()
    message["From"] = f"{config.MAIL_FROM_NAME} <{config.MAIL_FROM_EMAIL}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body)

    if html_body:
        message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    # Explicitly enforce TLS 1.2 or higher for security compliance
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    with smtplib.SMTP(config.MAIL_SMTP_HOST, config.MAIL_SMTP_PORT, timeout=30) as smtp:
        if config.MAIL_SMTP_USE_TLS:
            smtp.starttls(context=context)
        smtp.login(config.MAIL_SMTP_USERNAME, config.MAIL_SMTP_PASSWORD)
        smtp.send_message(message)


def _get_confirmation_content(
    to_email: str,
    subject: str | None,
    body: str | None,
    confirmation_url: str | None,
) -> tuple[str, str]:
    """Helper to generate subject and body from confirmation URL or direct inputs."""
    if confirmation_url:
        subject = subject or "Successfully signed up - Confirm your email for Task Buddy"
        body = (
            body
            or f"Hi {to_email}, please confirm your email by clicking the following link: {confirmation_url}"
        )

    if subject is None or body is None:
        raise ValueError("Either confirmation_url or subject and body must be provided")

    return subject, body


async def _record_confirmation_failure(to_email: str) -> None:
    """Helper to mark a user as having a failed email confirmation in the database."""
    try:
        async with AsyncSessionLocal() as db:
            stmt = update(User).where(User.email == to_email).values(confirmation_failed=True)
            await db.execute(stmt)
            await db.commit()
    except Exception:
        logger.exception("Failed to record confirmation failure for %s", to_email)


async def _send_confirmation_email_async(
    to_email: str,
    subject: str | None = None,
    body: str | None = None,
    confirmation_url: str | None = None,
    *,
    suppress_exceptions: bool = False,
) -> None:
    """Internal async implementation of confirmation email sending."""
    try:
        final_subject, final_body = _get_confirmation_content(
            to_email, subject, body, confirmation_url
        )
    except ValueError:
        if suppress_exceptions:
            logger.error("Invalid call to send_confirmation_email: missing content")
            return
        raise

    # 1. Try SMTP
    try:
        await asyncio.to_thread(send_smtp_email, to_email, final_subject, final_body)
        return
    except Exception:
        logger.warning(
            "SMTP email failed for %s; falling back to Brevo API", to_email, exc_info=True
        )

    # 2. Try Brevo API Fallback
    try:
        await send_brevo_email(to_email, final_subject, final_body)
    except Exception as api_error:
        logger.exception("Brevo API fallback failed for %s", to_email)

        # Record failure in DB as a last resort
        await _record_confirmation_failure(to_email)

        if not suppress_exceptions:
            raise APIResponseError(
                "Failed to send confirmation email via SMTP and Brevo API"
            ) from api_error


def run_async_coroutine(coro):
    """
    Helper to run an async coroutine from a synchronous context.
    If an event loop is already running (e.g., in tests), it runs the coroutine
    in a separate thread to avoid RuntimeError: asyncio.run() cannot be called from a running event loop.
    """
    try:
        asyncio.get_running_loop()
        # If we reach here, a loop is running. Run in a thread to block synchronously.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        # No loop running, safe to use asyncio.run
        return asyncio.run(coro)


@celery_app.task(
    name="app.tasks.send_confirmation_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3
)
def send_confirmation_email(
    to_email: str,
    subject: str | None = None,
    body: str | None = None,
    confirmation_url: str | None = None,
) -> None:
    """Celery task to send confirmation email."""
    run_async_coroutine(
        _send_confirmation_email_async(
            to_email, subject, body, confirmation_url, suppress_exceptions=True
        )
    )
async def _send_password_reset_email_async(
    to_email: str,
    reset_url: str,
    *,
    suppress_exceptions: bool = False,
) -> None:
    """Internal async implementation of password reset email sending."""
    from app.libs.email_templates import get_password_reset_html

    subject = "Password Reset Request - Task Buddy"
    text_body = f"Hi, you requested a password reset. Please use the following link to reset your password: {reset_url}"
    html_body = get_password_reset_html(reset_url)

    # 1. Try SMTP
    try:
        await asyncio.to_thread(send_smtp_email, to_email, subject, text_body, html_body)
        return
    except Exception:
        logger.warning(
            "SMTP email failed for %s; falling back to Brevo API", to_email, exc_info=True
        )

    # 2. Try Brevo API Fallback
    try:
        await send_brevo_email(to_email, subject, text_body, html_body)
    except Exception as api_error:
        logger.exception("Brevo API fallback failed for %s", to_email)
        if not suppress_exceptions:
            raise APIResponseError(
                "Failed to send password reset email via SMTP and Brevo API"
            ) from api_error


@celery_app.task(
    name="app.tasks.send_password_reset_email",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3
)
def send_password_reset_email(to_email: str, reset_url: str) -> None:
    """Celery task to send password reset email."""
    run_async_coroutine(_send_password_reset_email_async(to_email, reset_url, suppress_exceptions=True))

async def _send_password_changed_confirmation_async(
    to_email: str,
    *,
    suppress_exceptions: bool = False,
) -> None:
    """Internal async implementation of password changed confirmation email sending."""
    from app.libs.email_templates import get_password_changed_html

    subject = "Security Update: Password Changed - Task Buddy"
    text_body = f"Hi {to_email}, your Task Buddy password was successfully updated."
    html_body = get_password_changed_html(to_email)

    # 1. Try SMTP
    try:
        await asyncio.to_thread(send_smtp_email, to_email, subject, text_body, html_body)
        return
    except Exception:
        logger.warning(
            "SMTP email failed for %s; falling back to Brevo API", to_email, exc_info=True
        )

    # 2. Try Brevo API Fallback
    try:
        await send_brevo_email(to_email, subject, text_body, html_body)
    except Exception as api_error:
        logger.exception("Brevo API fallback failed for %s", to_email)
        if not suppress_exceptions:
            raise APIResponseError(
                "Failed to send password changed confirmation email via SMTP and Brevo API"
            ) from api_error


@celery_app.task(
    name="app.tasks.send_password_changed_confirmation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3
)
def send_password_changed_confirmation(to_email: str) -> None:
    """Celery task to send password changed confirmation email."""
    run_async_coroutine(
        _send_password_changed_confirmation_async(to_email, suppress_exceptions=True)
    )
