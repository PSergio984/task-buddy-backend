"""Transactional email HTML templates with output escaping.

All dynamic values (URLs, names, content) are HTML-escaped before being
embedded; URL values are additionally validated against the configured
frontend origin before use in href attributes.
"""

import html
import logging
from urllib.parse import urlparse

from app.config import config

logger = logging.getLogger(__name__)

_DEV_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Premium Brand Colors
BRAND_NAVY = "#0F172A"
BRAND_SLATE = "#F1F5F9"
BRAND_ACCENT = "#C2A388"
BRAND_WHITE = "#FFFFFF"


def _validate_safe_url(url: str) -> str:
    """Return the URL if it is https, or http on a local development host.

    Rejects javascript:, data:, file:, and non-local plain-http URLs so
    email templates can never navigate to attacker-controlled schemes.
    """
    try:
        parsed = urlparse(url)
    except ValueError as e:
        raise ValueError(f"Invalid URL in email template: {url!r}") from e

    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and parsed.hostname in _DEV_HOSTS:
        return url

    raise ValueError(f"URL not allowed in email template: {url!r}")


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def get_base_template(content_html: str) -> str:
    """Wrap content in the premium minimalist layout."""
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: 'Plus Jakarta Sans', Helvetica, Arial, sans-serif;
                background-color: {BRAND_SLATE};
                color: {BRAND_NAVY};
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: {BRAND_WHITE};
                border-radius: 24px;
                padding: 48px;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            }}
            .logo {{
                margin-bottom: 32px;
                font-weight: 800;
                letter-spacing: -0.025em;
                text-transform: uppercase;
                color: {BRAND_NAVY};
                font-size: 20px;
            }}
            .content {{
                line-height: 1.6;
                font-size: 16px;
            }}
            .footer {{
                margin-top: 48px;
                font-size: 12px;
                color: #64748b;
                text-align: center;
            }}
            .button {{
                display: inline-block;
                padding: 14px 28px;
                background-color: {BRAND_ACCENT};
                color: {BRAND_WHITE} !important;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 700;
                margin-top: 24px;
                transition: transform 0.2s ease;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">Task Buddy</div>
            <div class="content">
                {content_html}
            </div>
            <div class="footer">
                &copy; {_escape(config.MAIL_FROM_NAME)}. Premium Task Management.
            </div>
        </div>
    </body>
    </html>
    """


def get_password_reset_html(reset_url: str) -> str:
    """Render the password-reset email with a validated, escaped reset link."""
    safe_url = _escape(_validate_safe_url(reset_url))
    content = f"""
    <h1 style="margin-top: 0; font-size: 24px; font-weight: 800;">Password Reset Request</h1>
    <p>We received a request to reset your password. If this was you, please click the button below to secure your account.</p>
    <a href="{safe_url}" class="button">Reset Password</a>
    <p style="margin-top: 32px; font-size: 14px; color: #64748b;">
        If you didn't request this, you can safely ignore this email. This link will expire in {config.RESET_TOKEN_EXPIRE_MINUTES} minutes.
    </p>
    """
    return get_base_template(content)


def get_password_changed_html(user_email: str) -> str:
    """Render the password-changed email with the user's escaped email."""
    content = f"""
    <h1 style="margin-top: 0; font-size: 24px; font-weight: 800;">Security Update</h1>
    <p>Hi {_escape(user_email)},</p>
    <p>Your password was successfully updated. Your account is now secured with the new credentials.</p>
    <p>If you did not authorize this change, please contact our security team immediately.</p>
    """
    return get_base_template(content)


def get_confirmation_html(confirmation_url: str) -> str:
    """Render the email-confirmation email with a validated, escaped link."""
    safe_url = _escape(_validate_safe_url(confirmation_url))
    content = f"""
    <h1 style="margin-top: 0; font-size: 24px; font-weight: 800;">Welcome to Task Buddy!</h1>
    <p>We're thrilled to have you here. To get started and unlock the full potential of premium task management, please verify your email address.</p>
    <a href="{safe_url}" class="button">Verify Email</a>
    <p style="margin-top: 32px; font-size: 14px; color: #64748b;">
        If you didn't create an account, you can safely ignore this email.
    </p>
    """
    return get_base_template(content)
