import logging

import httpx

from app.config import config

logger = logging.getLogger(__name__)


class APIResponseError(Exception):
    pass


async def send_email(to_email: str, subject: str, body: str) -> httpx.Response:
    try:
        if not config.MAIL_URL or not (
            config.MAIL_URL.startswith("http://") or config.MAIL_URL.startswith("https://")
        ):
            raise APIResponseError(
                f"Invalid MAIL_URL: {config.MAIL_URL}. Must start with http:// or https://"
            )
        if not config.MAIL_API_KEY:
            raise APIResponseError("Missing MAIL_API_KEY for Brevo transactional email")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                config.MAIL_URL,
                headers={
                    "api-key": config.MAIL_API_KEY,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json={
                    "sender": {"email": "hello@taskbuddy.com", "name": "Task Buddy"},
                    "to": [{"email": to_email}],
                    "subject": subject,
                    "textContent": body,
                },
            )
            response.raise_for_status()

            return response

    except Exception as e:
        # Support various httpx exception types and absence of a response attribute.
        resp = getattr(e, "response", None)
        status_code = getattr(resp, "status_code", None)
        if status_code is not None:
            raise APIResponseError(f"API request failed: with status code {status_code}") from e
        raise APIResponseError("API request failed") from e


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
        return await send_email(to_email, subject, body)
    except Exception as e:
        # Log full stack and message
        logger.exception("Failed to send confirmation email to %s", to_email)

        # Attempt to record failure state in the database; if that fails, log and continue
        try:
            from app.database import database, tbl_user

            query = (
                tbl_user.update()
                .where(tbl_user.c.email == to_email)
                .values(confirmation_failed=True)
            )
            # database may or may not be connected depending on execution context
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
        # Re-raise a domain-specific error for callers that expect exceptions
        raise APIResponseError("Failed to send confirmation email") from e
