import asyncio
import os
import sys

# Add the current directory to sys.path so we can import app
sys.path.append(os.getcwd())

from app.config import config
from app.tasks import APIResponseError, send_brevo_email, send_smtp_email


async def test_email(target_email: str, test_type: str = "simple"):
    print(f"--- Email Delivery Test: {test_type.upper()} ---")
    print(f"Env State: {config.ENV_STATE}")
    print(f"SMTP Host: {config.MAIL_SMTP_HOST}")
    print(f"Sender: {config.MAIL_FROM_NAME} <{config.MAIL_FROM_EMAIL}>")

    if test_type == "confirmation":
        subject = "Successfully signed up - Confirm your email for Task Buddy"
        text_body = "Please confirm your email by clicking: http://localhost:5173/confirm/test-token"
        from app.libs.email_templates import get_confirmation_html
        html_body = get_confirmation_html("http://localhost:5173/confirm/test-token")
    elif test_type == "reset":
        subject = "Password Reset Request - Task Buddy"
        text_body = "Reset your password at: http://localhost:5173/reset/test-token"
        from app.libs.email_templates import get_password_reset_html
        html_body = get_password_reset_html("http://localhost:5173/reset/test-token")
    else:
        subject = "Task Buddy - Simple Connectivity Test"
        text_body = "If you are reading this, your email configuration is working perfectly!"
        html_body = f"<h1>Success!</h1><p>{text_body}</p>"

    try:
        print(f"Attempting to send via SMTP ({config.MAIL_SMTP_HOST})...")
        send_smtp_email(target_email, subject, text_body, html_body)
        print(f"[SUCCESS] {test_type.capitalize()} Email sent successfully!")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_email_delivery.py <your-email> [type: simple|confirmation|reset]")
        sys.exit(1)

    email_to = sys.argv[1]
    test_type = sys.argv[2] if len(sys.argv) > 2 else "simple"
    asyncio.run(test_email(email_to, test_type))
