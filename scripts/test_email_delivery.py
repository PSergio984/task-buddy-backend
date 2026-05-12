import asyncio
import os
import sys

# Add the current directory to sys.path so we can import app
sys.path.append(os.getcwd())

from app.config import config
from app.tasks import APIResponseError, send_brevo_email, send_smtp_email


async def test_email(target_email: str):
    print("--- Email Delivery Test ---")
    print(f"Env State: {config.ENV_STATE}")
    print(f"SMTP Host: {config.MAIL_SMTP_HOST}")
    print(f"SMTP User: {config.MAIL_SMTP_USERNAME}")
    print(f"Sender Email: {config.MAIL_FROM_EMAIL}")
    print(f"Frontend URL: {config.FRONTEND_URL}")

    subject = "Task Buddy - Local Dev Test Email"
    text_body = "If you are reading this, your email configuration is working perfectly!"
    html_body = f"<h1>Success!</h1><p>{text_body}</p><p>Links will point to: {config.FRONTEND_URL}</p>"

    try:
        if config.MAIL_SMTP_HOST:
            print(f"Attempting to send via SMTP ({config.MAIL_SMTP_HOST})...")
            # SMTP is synchronous in our tasks.py
            send_smtp_email(target_email, subject, text_body, html_body)
            print("[SUCCESS] SMTP Email sent successfully!")
        elif config.MAIL_API_KEY:
            print(f"Attempting to send via Brevo API ({config.MAIL_URL})...")
            await send_brevo_email(target_email, subject, text_body, html_body)
            print("[SUCCESS] API Email sent successfully!")
        else:
            print("[ERROR] No email configuration found in .env (need MAIL_SMTP_HOST or MAIL_API_KEY)")
            return
    except APIResponseError as e:
        print(f"[FAILED] Failed to send email: {e}")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")

if __name__ == "__main__":
    # Get email from command line or use your gmail as default
    email_to = sys.argv[1] if len(sys.argv) > 1 else "eric.manabatseam@gmail.com"
    asyncio.run(test_email(email_to))
