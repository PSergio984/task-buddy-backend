import httpx
import pytest

from app.tasks import APIResponseError, send_confirmation_email


@pytest.mark.anyio
async def test_send_confirmation_email(mock_httpx_client):
    await send_confirmation_email("test@example.com", "Test Subject", "Test Body")
    mock_httpx_client.post.assert_called_once()
    _, kwargs = mock_httpx_client.post.call_args
    assert kwargs["json"] == {
        "sender": {"email": "hello@taskbuddy.com", "name": "Task Buddy"},
        "to": [{"email": "test@example.com"}],
        "subject": "Test Subject",
        "textContent": "Test Body",
    }
    assert kwargs["headers"]["api-key"] is not None
    assert kwargs["headers"]["accept"] == "application/json"
    assert kwargs["headers"]["content-type"] == "application/json"


@pytest.mark.anyio
async def test_send_confirmation_email_api_error(mock_httpx_client):
    # Construct an HTTPStatusError with a response to simulate a 500 from the API
    mock_httpx_client.post.side_effect = httpx.HTTPStatusError(
        "Server error", request=httpx.Request("POST", "/"), response=httpx.Response(500)
    )
    with pytest.raises(APIResponseError):
        await send_confirmation_email("test@example.com", "Test Subject", "Test Body")
