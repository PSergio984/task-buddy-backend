"""Tests for the Supabase Realtime token endpoint and signing-key cache."""

import base64
import datetime
import json
import uuid
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import AsyncClient

from app.libs.supabase_signing import b64u_decode


def _b64u(data: bytes) -> str:
    """Base64url without padding (JWK component encoding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_test_jwk() -> dict[str, Any]:
    """Generate a fresh ES256 keypair JWK at runtime (never commit private keys)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public = private_key.public_key().public_numbers()
    private = private_key.private_numbers()
    jwk_data = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64u(public.x.to_bytes(32, "big")),
        "y": _b64u(public.y.to_bytes(32, "big")),
        "d": _b64u(private.private_value.to_bytes(32, "big")),
        "kid": str(uuid.uuid4()),
        "alg": "ES256",
        "use": "sig",
    }
    return jwk_data


def _public_key_for(jwk_data: dict[str, Any]) -> ec.EllipticCurvePublicKey:
    x = int.from_bytes(b64u_decode(jwk_data["x"]), "big")
    y = int.from_bytes(b64u_decode(jwk_data["y"]), "big")
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()


def _write_key(tmp_path: Path, jwk_data: dict[str, Any]) -> Path:
    key_file = tmp_path / "signing_key.json"
    key_file.write_text(json.dumps(jwk_data))
    return key_file


@pytest.fixture()
def signing_key_file(mocker, tmp_path: Path) -> Path:
    """Write a runtime-generated signing key JWK and point config at it."""
    from app.api.routers import realtime

    key_file = _write_key(tmp_path, _make_test_jwk())
    mocker.patch.object(realtime.config, "SUPABASE_SIGNING_KEY_FILE", str(key_file))
    return key_file


@pytest.mark.anyio
async def test_realtime_token_unauthorized(async_client: AsyncClient) -> None:
    response = await async_client.post("/api/v1/realtime/token")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_realtime_token_authorized(
    authenticated_async_client: AsyncClient,
    confirmed_user: dict[str, Any],
    signing_key_file,
) -> None:
    from app.api.routers import realtime

    jwk_data = json.loads(signing_key_file.read_text())

    response = await authenticated_async_client.post("/api/v1/realtime/token")
    assert response.status_code == 200
    payload = response.json()
    assert "token" in payload
    assert payload["expires_in"] == realtime.config.SUPABASE_REALTIME_TOKEN_EXPIRE_SECONDS

    decoded = jwt.decode(payload["token"], _public_key_for(jwk_data), algorithms=["ES256"])
    assert decoded["role"] == "authenticated"
    assert decoded["sub"] == str(confirmed_user["id"])
    exp = datetime.datetime.fromtimestamp(decoded["exp"], tz=datetime.timezone.utc)
    assert exp > datetime.datetime.now(datetime.timezone.utc)
    assert exp - datetime.datetime.now(datetime.timezone.utc) <= datetime.timedelta(
        seconds=realtime.config.SUPABASE_REALTIME_TOKEN_EXPIRE_SECONDS
    )

    header = jwt.get_unverified_header(payload["token"])
    assert header["alg"] == "ES256"
    assert header["kid"] == jwk_data["kid"]


@pytest.mark.anyio
async def test_realtime_token_missing_key(
    authenticated_async_client: AsyncClient, mocker, tmp_path
) -> None:
    from app.api.routers import realtime

    mocker.patch.object(
        realtime.config, "SUPABASE_SIGNING_KEY_FILE", str(tmp_path / "missing.json")
    )

    response = await authenticated_async_client.post("/api/v1/realtime/token")
    assert response.status_code == 500
    assert "signing_key.json" not in response.text
    assert "missing.json" not in response.text


@pytest.mark.anyio
async def test_realtime_token_rate_limited(
    authenticated_async_client: AsyncClient, signing_key_file
) -> None:
    from app.api.routers import realtime
    from app.main import app

    limiter_enabled = app.state.limiter.enabled
    app.state.limiter.enabled = True
    app.state.limiter.reset()
    try:
        limit = int(realtime.config.RATE_LIMIT_REALTIME_TOKEN.split("/")[0])
        statuses = []
        for _ in range(limit + 1):
            response = await authenticated_async_client.post("/api/v1/realtime/token")
            statuses.append(response.status_code)
        assert statuses[-1] == 429
    finally:
        app.state.limiter.reset()
        app.state.limiter.enabled = limiter_enabled


def test_signing_key_cache_invalidated_on_rotation(tmp_path) -> None:
    """A file swap (dashboard key rotation) must invalidate the cache."""
    from app.libs.supabase_signing import SigningKeyCache

    cache = SigningKeyCache()
    first_jwk = _make_test_jwk()
    key_file = _write_key(tmp_path, first_jwk)

    first = cache.load(str(key_file))
    assert first.kid == first_jwk["kid"]

    rotated_jwk = _make_test_jwk()
    key_file.write_text(json.dumps(rotated_jwk))
    rotated = cache.load(str(key_file))
    assert rotated.kid == rotated_jwk["kid"]
    assert rotated.kid != first.kid


def test_signing_key_rejects_invalid_shape(tmp_path) -> None:
    from app.libs.supabase_signing import SigningKeyCache

    cache = SigningKeyCache()
    bad_jwk = _make_test_jwk()
    bad_jwk["kty"] = "RSA"
    key_file = _write_key(tmp_path, bad_jwk)

    with pytest.raises(ValueError):
        cache.load(str(key_file))


def test_signing_key_rejects_mismatched_public_values(tmp_path) -> None:
    from app.libs.supabase_signing import SigningKeyCache

    cache = SigningKeyCache()
    bad_jwk = _make_test_jwk()
    other_jwk = _make_test_jwk()
    bad_jwk["x"] = other_jwk["x"]
    bad_jwk["y"] = other_jwk["y"]
    key_file = _write_key(tmp_path, bad_jwk)

    with pytest.raises(ValueError):
        cache.load(str(key_file))


def test_signing_key_missing_kid_rejected(tmp_path) -> None:
    from app.libs.supabase_signing import SigningKeyCache

    cache = SigningKeyCache()
    bad_jwk = _make_test_jwk()
    del bad_jwk["kid"]
    key_file = _write_key(tmp_path, bad_jwk)

    with pytest.raises(ValueError):
        cache.load(str(key_file))


def test_signing_key_rejects_non_string_components(tmp_path) -> None:
    from app.libs.supabase_signing import SigningKeyCache

    cache = SigningKeyCache()
    bad_jwk = _make_test_jwk()
    bad_jwk["d"] = 12345
    key_file = _write_key(tmp_path, bad_jwk)

    with pytest.raises(ValueError):
        cache.load(str(key_file))


@pytest.mark.anyio
async def test_stream_endpoint_removed(
    authenticated_async_client: AsyncClient, signing_key_file: Any
) -> None:
    """The dead SSE /stream endpoint was removed; it must 404 (audit #28)."""
    response = await authenticated_async_client.get("/api/v1/realtime/stream")
    assert response.status_code == 404
