from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid

vapid = Vapid()
vapid.generate_keys()
# It doesn't seem to have a simple way to export as string directly from object without saving to file or using internal methods.
# Actually it has sign_key and public_key attributes which are cryptography objects.

private_key = vapid.private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption()
).decode('utf-8')

# For WebPush, often we want the Base64 encoded uncompressed point for the public key.
# But pywebpush might take the PEM or DER.
# Let's see what pywebpush needs.
print("Keys generated successfully (internal objects)")
