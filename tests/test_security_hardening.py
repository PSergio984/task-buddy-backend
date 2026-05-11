from httpx import AsyncClient

from app.main import app


async def test_security_headers(async_client: AsyncClient):
    response = await async_client.get("/api/v1/tasks")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    # X-XSS-Protection is deprecated and removed
    assert "X-XSS-Protection" not in response.headers
    assert "Content-Security-Policy" in response.headers
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "https://cdn.jsdelivr.net" in csp
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in response.headers
    assert "geolocation=()" in response.headers["Permissions-Policy"]

async def test_cors_allowed_origin(async_client: AsyncClient):
    # Default allowed origin is http://localhost:3000
    headers = {"Origin": "http://localhost:3000"}
    response = await async_client.options("/api/v1/users/register", headers=headers)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

async def test_cors_disallowed_origin(async_client: AsyncClient):
    headers = {"Origin": "http://evil.com"}
    response = await async_client.options("/api/v1/users/register", headers=headers)
    assert "access-control-allow-origin" not in response.headers or response.headers["access-control-allow-origin"] != "http://evil.com"

async def test_rate_limiting_register(async_client: AsyncClient, mocker):
    # Enable limiter specifically for this test
    app.state.limiter.enabled = True
    try:
        # Mock get_remote_address to ensure we have a consistent key
        mocker.patch("app.limiter.get_remote_address", return_value="127.0.0.1")

        user_data = {
            "username": "ratelimituser",
            "email": "ratelimit@example.com",
            "password": "testpassword",
        }

        # Hit the limit (5 per minute)
        for _ in range(5):
            response = await async_client.post("/api/v1/users/register", json=user_data)
            # We don't care about the result here, just that it's not 429
            assert response.status_code != 429

        # 6th request should be rate limited
        response = await async_client.post("/api/v1/users/register", json=user_data)
        assert response.status_code == 429
        # Our custom handler uses "detail" to match FastAPI defaults
        resp_json = response.json()
        assert "detail" in resp_json
        assert "Too many attempts" in resp_json["detail"]
    finally:
        app.state.limiter.enabled = False

async def test_rate_limiting_create_project(async_client: AsyncClient, mocker, authenticated_async_client: AsyncClient):
    # Enable limiter specifically for this test
    app.state.limiter.enabled = True
    try:
        # Mock get_remote_address to ensure we have a consistent key
        mocker.patch("app.limiter.get_remote_address", return_value="127.0.0.1")

        project_data = {
            "name": "Rate Limit Project",
            "description": "Test description",
        }

        # Hit the limit (10 per minute)
        for _ in range(10):
            response = await authenticated_async_client.post("/api/v1/projects/", json=project_data)
            # We don't care about the result here (could be 201 or 400 if name taken), just not 429
            assert response.status_code != 429

        # 11th request should be rate limited
        response = await authenticated_async_client.post("/api/v1/projects/", json=project_data)
        assert response.status_code == 429
        resp_json = response.json()
        assert "detail" in resp_json
        assert "Too many attempts" in resp_json["detail"]
    finally:
        app.state.limiter.enabled = False


async def test_rate_limiting_login(async_client: AsyncClient, mocker):
    # Enable limiter specifically for this test
    app.state.limiter.enabled = True
    try:
        # Mock get_remote_address to ensure we have a consistent key
        mocker.patch("app.limiter.get_remote_address", return_value="127.0.0.1")

        login_data = {
            "username": "nonexistentuser@example.com",
            "password": "wrongpassword",
        }

        # Hit the limit (5 per minute)
        for _ in range(5):
            # We use data= because OAuth2PasswordRequestForm expects form data
            response = await async_client.post("/api/v1/users/token", data=login_data)
            # Should be 401 Unauthorized for wrong credentials, but not 429
            assert response.status_code == 401

        # 6th request should be rate limited
        response = await async_client.post("/api/v1/users/token", data=login_data)
        assert response.status_code == 429
        resp_json = response.json()
        assert "detail" in resp_json
        assert "Too many attempts" in resp_json["detail"]
    finally:
        app.state.limiter.enabled = False

