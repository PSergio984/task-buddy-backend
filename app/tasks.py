import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from app.config import config

logger = logging.getLogger(__name__)


class APIResponseError(Exception):
    pass


def _is_valid_url(url: str | None) -> bool:
    """Helper to validate that a URL starts with http:// or https://."""
    return bool(url and (url.startswith("http://") or url.startswith("https://")))


async def send_brevo_email(to_email: str, subject: str, body: str) -> httpx.Response:
    if not _is_valid_url(config.MAIL_URL):
        raise APIResponseError(
            f"Invalid MAIL_URL: {config.MAIL_URL}. Must start with http:// or https://"
        )
    if not config.MAIL_API_KEY:
        raise APIResponseError("Missing MAIL_API_KEY for Brevo transactional email")
    if not config.MAIL_FROM_EMAIL:
        raise APIResponseError("Missing MAIL_FROM_EMAIL for Brevo transactional email")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            config.MAIL_URL,
            headers={
                "api-key": config.MAIL_API_KEY,
                "accept": "application/json",
                "content-type": "application/json",
            },
            json={
                "sender": {"email": config.MAIL_FROM_EMAIL, "name": config.MAIL_FROM_NAME},
                "to": [{"email": to_email}],
                "subject": subject,
                "textContent": body,
            },
        )
        response.raise_for_status()
        return response


def send_smtp_email(to_email: str, subject: str, body: str) -> None:
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
    message.set_content(body)

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
        from app.database import database, tbl_user

        query = (
            tbl_user.update()
            .where(tbl_user.c.email == to_email)
            .values(confirmation_failed=True)
        )
        # Ensure database is connected for this standalone operation if called from background task
        if not database.is_connected:
            await database.connect()
            await database.execute(query)
            await database.disconnect()
        else:
            await database.execute(query)
    except Exception:
        logger.exception("Failed to record confirmation failure for %s", to_email)


async def send_confirmation_email(
    to_email: str,
    subject: str | None = None,
    body: str | None = None,
    confirmation_url: str | None = None,
    *,
    suppress_exceptions: bool = False,
) -> None:
    """Send a confirmation email with SMTP and Brevo API fallback.

    The logic is broken down to reduce cognitive complexity.
    """
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
