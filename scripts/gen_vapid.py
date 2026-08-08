"""Generate VAPID keys for web-push.

Prints only the public key to stdout; the private key is written to a
file with owner-only permissions (path from VAPID_PRIVATE_KEY_FILE or
defaults to ./vapid_private_key.json). Never print the private key.
"""

import json
import os
from pathlib import Path

from pywebpush import vapid_keys


def main() -> None:
    keys = vapid_keys.generate_vapid_keys()
    public_key = keys["public_key"]
    private_key = keys["private_key"]

    out_path = Path(os.environ.get("VAPID_PRIVATE_KEY_FILE", "vapid_private_key.json"))
    out_path.write_text(json.dumps({"private_key": private_key}))
    try:
        out_path.chmod(0o600)
    except OSError:
        pass  # Windows: chmod is a no-op; file is protected via user ACLs

    print(f"VAPID_PUBLIC_KEY={public_key}")
    print(f"Private key saved to {out_path} (owner-only, not printed)")


if __name__ == "__main__":
    main()
