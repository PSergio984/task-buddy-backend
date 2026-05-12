import asyncio
import json
import logging
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import httpx
from pywebpush import WebPushException, webpush
from sqlalchemy import exists, select, update

from app.celery_app import celery_app
from app.config import config
from app.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType, PushSubscription
from app.models.task import Task
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

    with smtplib.SMTP(config.MAIL_SMTP_HOST, config.MAIL_SMTP_PORT, timeout=5) as smtp:
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
    from app.libs.email_templates import get_confirmation_html

    try:
        final_subject, text_body = _get_confirmation_content(
            to_email, subject, body, confirmation_url
        )
        html_body = get_confirmation_html(confirmation_url) if confirmation_url else None
    except ValueError:
        if suppress_exceptions:
            logger.error("Invalid call to send_confirmation_email: missing content")
            return
        raise

    # 1. Try Brevo API (Faster and more reliable on cloud platforms like Render)
    try:
        await send_brevo_email(to_email, final_subject, text_body, html_body)
        return
    except Exception:
        logger.warning(
            "Brevo API email failed for %s; falling back to SMTP", to_email, exc_info=True
        )

    # 2. Try SMTP Fallback
    try:
        await asyncio.to_thread(send_smtp_email, to_email, final_subject, text_body, html_body)
    except Exception as smtp_error:
        logger.exception("SMTP fallback failed for %s", to_email)

        # Record failure in DB as a last resort
        await _record_confirmation_failure(to_email)

        if not suppress_exceptions:
            raise APIResponseError(
                "Failed to send confirmation email via Brevo API and SMTP"
            ) from smtp_error


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

    # 1. Try Brevo API (Faster and more reliable on cloud platforms like Render)
    try:
        await send_brevo_email(to_email, subject, text_body, html_body)
        return
    except Exception:
        logger.warning(
            "Brevo API email failed for %s; falling back to SMTP", to_email, exc_info=True
        )

    # 2. Try SMTP Fallback
    try:
        await asyncio.to_thread(send_smtp_email, to_email, subject, text_body, html_body)
    except Exception as smtp_error:
        logger.exception("SMTP fallback failed for %s", to_email)
        if not suppress_exceptions:
            raise APIResponseError(
                "Failed to send email via Brevo API and SMTP"
            ) from smtp_error


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

    # 1. Try Brevo API (Faster and more reliable on cloud platforms like Render)
    try:
        await send_brevo_email(to_email, subject, text_body, html_body)
        return
    except Exception:
        logger.warning(
            "Brevo API email failed for %s; falling back to SMTP", to_email, exc_info=True
        )

    # 2. Try SMTP Fallback
    try:
        await asyncio.to_thread(send_smtp_email, to_email, subject, text_body, html_body)
    except Exception as smtp_error:
        logger.exception("SMTP fallback failed for %s", to_email)
        if not suppress_exceptions:
            raise APIResponseError(
                "Failed to send email via Brevo API and SMTP"
            ) from smtp_error


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


@celery_app.task(name="app.tasks.process_reminders")
def process_reminders() -> None:
    """Celery task to scan for upcoming/overdue tasks and send notifications."""
    run_async_coroutine(_process_reminders_async())


async def _process_reminders_async() -> None:
    now = datetime.now(timezone.utc)

    # Define windows for scanning
    windows = [
        {
            "type": NotificationType.REMINDER_BEFORE,
            "start": now + timedelta(minutes=50),
            "end": now + timedelta(minutes=70),
            "title": "Upcoming Task: {title}",
            "message": "Your task '{title}' is due in 1 hour."
        },
        {
            "type": NotificationType.REMINDER_DUE,
            "start": now - timedelta(minutes=10),
            "end": now + timedelta(minutes=10),
            "title": "Task Due Now: {title}",
            "message": "Your task '{title}' is due now."
        },
        {
            "type": NotificationType.REMINDER_OVERDUE,
            "start": now - timedelta(hours=24, minutes=10),
            "end": now - timedelta(hours=23, minutes=50),
            "title": "Task Overdue: {title}",
            "message": "Your task '{title}' is 24 hours overdue."
        }
    ]

    async with AsyncSessionLocal() as db:
        # Optimization: only query tasks with due dates in the broadest possible range
        min_start = now - timedelta(hours=24, minutes=10)
        max_end = now + timedelta(minutes=70)

        stmt = select(Task).where(
            not Task.completed,
            Task.due_date >= min_start,
            Task.due_date <= max_end
        )
        result = await db.execute(stmt)
        tasks = result.scalars().all()

        for task in tasks:
            for window in windows:
                # Ensure task.due_date is timezone aware for comparison
                task_due_date = task.due_date
                if task_due_date and task_due_date.tzinfo is None:
                    task_due_date = task_due_date.replace(tzinfo=timezone.utc)

                if task_due_date and window["start"] <= task_due_date <= window["end"]:
                    # Deduplication: Check if notification already exists for this task and type
                    exists_stmt = select(exists().where(
                        Notification.task_id == task.id,
                        Notification.type == window["type"]
                    ))
                    already_notified = (await db.execute(exists_stmt)).scalar()

                    if not already_notified:
                        title = window["title"].format(title=task.title)
                        message = window["message"].format(title=task.title)
                        action_url = f"/tasks/{task.id}"

                        # 1. Create In-App Notification
                        notification = Notification(
                            user_id=task.user_id,
                            task_id=task.id,
                            type=window["type"],
                            title=title,
                            message=message,
                            action_url=action_url
                        )
                        db.add(notification)

                        # 2. Enqueue Push Notification
                        send_push_notification.delay(task.user_id, title, message, action_url)

                        # 3. Enqueue Email Notification
                        user_stmt = select(User.email).where(User.id == task.user_id)
                        user_email = (await db.execute(user_stmt)).scalar()
                        if user_email:
                            send_confirmation_email.delay(user_email, title, message)

        await db.commit()


@celery_app.task(
    name="app.tasks.send_push_notification",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3
)
def send_push_notification(user_id: int, title: str, message: str, action_url: str | None = None) -> None:
    """Celery task to send web push notifications to all user subscriptions."""
    run_async_coroutine(_send_push_notification_async(user_id, title, message, action_url))


async def _send_push_notification_async(user_id: int, title: str, message: str, action_url: str | None = None) -> None:
    if not config.VAPID_PRIVATE_KEY:
        logger.error("VAPID_PRIVATE_KEY not configured, cannot send push notifications")
        return

    async with AsyncSessionLocal() as db:
        stmt = select(PushSubscription).where(PushSubscription.user_id == user_id)
        result = await db.execute(stmt)
        subscriptions = result.scalars().all()

        if not subscriptions:
            return

        payload = json.dumps({
            "title": title,
            "body": message,
            "data": {
                "url": action_url
            }
        })

        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh,
                            "auth": sub.auth
                        }
                    },
                    data=payload,
                    vapid_private_key=config.VAPID_PRIVATE_KEY,
                    vapid_claims={
                        "sub": f"mailto:{config.VAPID_ADMIN_EMAIL}"
                    }
                )
            except WebPushException as ex:
                if ex.response is not None and ex.response.status_code == 410:
                    logger.info("Push subscription expired for endpoint %s; deleting", sub.endpoint)
                    await db.delete(sub)
                else:
                    logger.error("Failed to send push notification to %s: %s", sub.endpoint, str(ex))
            except Exception:
                logger.exception("Unexpected error sending push notification to %s", sub.endpoint)

        await db.commit()
