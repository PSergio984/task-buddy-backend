import httpx
import pytest

from app.tasks import APIResponseError, send_confirmation_email


@pytest.mark.anyio
async def test_send_confirmation_email(mock_httpx_client):
    await send_confirmation_email("test@example.com", "Test Subject", "Test Body")
    # Verify SMTP (primary path) was called
    mock_httpx_client.smtp.assert_called_once_with("smtp-relay.brevo.com", 587, timeout=30)
    mock_httpx_client.smtp_client.starttls.assert_called_once()
    mock_httpx_client.smtp_client.login.assert_called_once_with(
        "9d9828001@smtp-brevo.com", "test-smtp-password"
    )
    mock_httpx_client.smtp_client.send_message.assert_called_once()


@pytest.mark.anyio
async def test_send_confirmation_email_api_error(mock_httpx_client):
    # Force SMTP to fail so we exercise the Brevo API fallback
    mock_httpx_client.smtp_client.send_message.side_effect = OSError("SMTP failed")
    # Construct an HTTPStatusError to simulate a 500 from the API fallback
    mock_httpx_client.post.side_effect = httpx.HTTPStatusError(
        "Server error", request=httpx.Request("POST", "/"), response=httpx.Response(500)
    )

    with pytest.raises(APIResponseError):
        await send_confirmation_email("test@example.com", "Test Subject", "Test Body")


@pytest.mark.anyio
async def test_send_confirmation_email_falls_back_to_api(mock_httpx_client):
    # Force SMTP to fail so we exercise the Brevo API fallback
    mock_httpx_client.smtp_client.send_message.side_effect = OSError("SMTP failed")

    await send_confirmation_email("test@example.com", "Test Subject", "Test Body")

    # Verify SMTP was attempted first
    mock_httpx_client.smtp.assert_called_once_with("smtp-relay.brevo.com", 587, timeout=30)
    # Verify API was called as fallback
    mock_httpx_client.post.assert_called_once()
    _, kwargs = mock_httpx_client.post.call_args
    assert kwargs["json"] == {
        "sender": {"email": "test-sender@example.com", "name": "Task Buddy"},
        "to": [{"email": "test@example.com"}],
        "subject": "Test Subject",
        "textContent": "Test Body",
    }
