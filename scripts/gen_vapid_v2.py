"""Generate VAPID keys using py_vapid.

Prints only the public key; the private key is persisted to a file with
owner-only permissions (path from VAPID_PRIVATE_KEY_FILE or defaults to
./vapid_private_key.pem).
"""

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def main() -> None:
    vapid = Vapid()
    vapid.generate_keys()

    public_key = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    ).hex()

    private_pem = vapid.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    out_path = Path(os.environ.get("VAPID_PRIVATE_KEY_FILE", "vapid_private_key.pem"))
    out_path.write_text(private_pem)
    try:
        out_path.chmod(0o600)
    except OSError:
        pass  # Windows: chmod is a no-op; file is protected via user ACLs

    print(f"VAPID_PUBLIC_KEY={public_key}")
    print(f"Private key saved to {out_path} (owner-only, not printed)")


if __name__ == "__main__":
    main()
