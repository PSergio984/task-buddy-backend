import httpx
import pytest

from app.tasks import APIResponseError, send_confirmation_email


@pytest.mark.anyio
async def test_send_confirmation_email(mock_httpx_client):
    await send_confirmation_email("test@example.com", "Test Subject", "Test Body")
    mock_httpx_client.post.assert_called()


@pytest.mark.anyio
async def test_send_confirmation_email_api_error(mock_httpx_client):
    # Construct an HTTPStatusError with a response to simulate a 500 from the API
    mock_httpx_client.post.side_effect = httpx.HTTPStatusError(
        "Server error", request=httpx.Request("POST", "/"), response=httpx.Response(500)
    )
    with pytest.raises(APIResponseError):
        await send_confirmation_email("test@example.com", "Test Subject", "Test Body")
