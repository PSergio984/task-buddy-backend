from pywebpush import vapid_keys

keys = vapid_keys.generate_vapid_keys()
print(f"VAPID_PUBLIC_KEY={keys['public_key']}")
print(f"VAPID_PRIVATE_KEY={keys['private_key']}")
