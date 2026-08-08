"""Loading and caching of the Supabase ES256 signing key.

The project uses Supabase's signing-keys system (ECC P-256). The private
half of an imported keypair is stored as a JWK on disk; :class:`SigningKeyCache`
builds a cryptography key from the raw JWK coordinates and caches it keyed on
file mtime so dashboard key rotations are picked up without a restart.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Any, NamedTuple, Optional

from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)


class SigningKey(NamedTuple):
    """An ES256 private key with its JWK key identifier.

    Attributes:
        private_key: The elliptic-curve private key used to sign JWTs.
        kid: The JWK key identifier Supabase uses to verify the signature.
    """

    private_key: ec.EllipticCurvePrivateKey
    kid: str


class _CacheEntry(NamedTuple):
    key_file: str
    signing_key: SigningKey
    mtime_ns: int


class SigningKeyCache:
    """Process-lifetime cache for the signing key, invalidated by file mtime."""

    def __init__(self) -> None:
        self._cache: Optional[_CacheEntry] = None

    def load(self, key_file: str) -> SigningKey:
        """Load the ES256 private key from a JWK file.

        Returns (private key, kid). Raises ValueError if the file is missing,
        malformed, or missing the private component or kid. Cached per file
        path + mtime (nanosecond) so a file swap (key rotation) invalidates
        the cache.
        """
        path = Path(key_file)

        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError as e:
            raise ValueError("Supabase signing key file not found") from e

        if (
            self._cache is not None
            and self._cache.key_file == key_file
            and self._cache.mtime_ns == mtime_ns
        ):
            return self._cache.signing_key

        try:
            signing_key = _load_key_from_file(path)
            self._cache = _CacheEntry(
                key_file=key_file, signing_key=signing_key, mtime_ns=mtime_ns
            )
            logger.debug("Loaded Supabase signing key (kid=%s)", signing_key.kid)
        except (KeyError, ValueError) as e:
            raise ValueError("Supabase signing key file unreadable") from e

        return signing_key


def _load_key_from_file(path: Path) -> SigningKey:
    jwk_data = _read_jwk(path)
    _validate_jwk_shape(jwk_data)

    d = int.from_bytes(b64u_decode(jwk_data["d"]), "big")
    private_key = ec.derive_private_key(d, ec.SECP256R1())

    public_numbers = private_key.public_key().public_numbers()
    x = int.from_bytes(b64u_decode(jwk_data["x"]), "big")
    y = int.from_bytes(b64u_decode(jwk_data["y"]), "big")
    if public_numbers.x != x or public_numbers.y != y:
        raise ValueError("Supabase signing key public values do not match")

    kid = jwk_data.get("kid")
    if not isinstance(kid, str) or not kid:
        raise ValueError("Supabase signing key file missing 'kid'")

    return SigningKey(private_key=private_key, kid=kid)


def _validate_jwk_shape(jwk_data: dict[str, Any]) -> None:
    if (
        jwk_data.get("kty") != "EC"
        or jwk_data.get("crv") != "P-256"
        or jwk_data.get("alg") != "ES256"
    ):
        raise ValueError("Supabase signing key file has an invalid key type")


def b64u_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _read_jwk(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError("Supabase signing key file unreadable") from e

    if not isinstance(data, dict):
        raise ValueError("Supabase signing key file must contain a JSON object")

    return data
