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


async def send_brevo_email(to_email: str, subject: str, body: str) -> httpx.Response:
    if not config.MAIL_URL or not (
        config.MAIL_URL.startswith("http://") or config.MAIL_URL.startswith("https://")
    ):
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
    with smtplib.SMTP(config.MAIL_SMTP_HOST, config.MAIL_SMTP_PORT, timeout=30) as smtp:
        if config.MAIL_SMTP_USE_TLS:
            smtp.starttls(context=context)
        smtp.login(config.MAIL_SMTP_USERNAME, config.MAIL_SMTP_PASSWORD)
        smtp.send_message(message)


async def send_confirmation_email(
    to_email: str,
    subject: str | None = None,
    body: str | None = None,
    confirmation_url: str | None = None,
    *,
    suppress_exceptions: bool = False,
) -> None:
    """Send a confirmation email.

    Call patterns supported:
    - send_confirmation_email(to_email, confirmation_url=...)
    - send_confirmation_email(to_email, subject, body)

    When `suppress_exceptions=True` the function will catch exceptions, log them,
    and record a failure state for the user instead of raising.
    """
    if confirmation_url:
        subject = subject or "Successfully signed up - Confirm your email for Task Buddy"
        body = (
            body
            or f"Hi {to_email}, please confirm your email by clicking the following link: {confirmation_url}"
        )

    if subject is None or body is None:
        raise ValueError("Either confirmation_url or subject and body must be provided")

    try:
        await asyncio.to_thread(send_smtp_email, to_email, subject, body)
        return None
    except Exception:
        logger.warning(
            "SMTP email failed for %s; falling back to Brevo API", to_email, exc_info=True
        )
        try:
            return await send_brevo_email(to_email, subject, body)
        except Exception as api_error:
            logger.exception("Brevo API fallback failed for %s", to_email)

            try:
                from app.database import database, tbl_user

                query = (
                    tbl_user.update()
                    .where(tbl_user.c.email == to_email)
                    .values(confirmation_failed=True)
                )
                if not database.is_connected:
                    await database.connect()
                    await database.execute(query)
                    await database.disconnect()
                else:
                    await database.execute(query)
            except Exception:
                logger.exception("Failed to record confirmation failure for %s", to_email)

            if suppress_exceptions:
                return None
            raise APIResponseError(
                "Failed to send confirmation email via SMTP and Brevo API"
            ) from api_error
