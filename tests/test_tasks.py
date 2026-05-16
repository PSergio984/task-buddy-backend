import httpx
import pytest

from app.tasks import APIResponseError, _send_confirmation_email_async, send_confirmation_email


def test_send_confirmation_email(mock_httpx_client):
    send_confirmation_email("test@example.com", "Test Subject", "Test Body")
    # Verify Brevo API (primary path) was called
    mock_httpx_client.post.assert_called_once()
    _, kwargs = mock_httpx_client.post.call_args
    assert kwargs["json"] == {
        "sender": {"email": "test-sender@example.com", "name": "Task Buddy"},
        "to": [{"email": "test@example.com"}],
        "subject": "Test Subject",
        "textContent": "Test Body",
    }
    # SMTP should NOT have been called
    mock_httpx_client.smtp.assert_not_called()


async def test_send_confirmation_email_api_error(mock_httpx_client):
    # Force Brevo API to fail so we exercise the SMTP fallback
    mock_httpx_client.post.side_effect = httpx.HTTPStatusError(
        "Server error", request=httpx.Request("POST", "/"), response=httpx.Response(500)
    )
    # Force SMTP to also fail
    mock_httpx_client.smtp_client.send_message.side_effect = OSError("SMTP failed")

    with pytest.raises(APIResponseError):
        # We call the async implementation directly to test error handling
        await _send_confirmation_email_async("test@example.com", "Test Subject", "Test Body", suppress_exceptions=False)


def test_send_confirmation_email_falls_back_to_smtp(mock_httpx_client):
    # Force Brevo API to fail
    mock_httpx_client.post.side_effect = httpx.HTTPStatusError(
        "Server error", request=httpx.Request("POST", "/"), response=httpx.Response(500)
    )

    send_confirmation_email("test@example.com", "Test Subject", "Test Body")

    # Verify API was attempted first
    mock_httpx_client.post.assert_called_once()
    # Verify SMTP was called as fallback
    mock_httpx_client.smtp.assert_called_once_with("smtp-relay.brevo.com", 587, timeout=5)
