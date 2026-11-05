"""Generate the key pair for web push notifications. Run once:

    python scripts/generate_vapid_keys.py

Never change them afterwards, or every owner's phone has to re-enable
notifications.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


key = ec.generate_private_key(ec.SECP256R1())
private = key.private_numbers().private_value.to_bytes(32, "big")
public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
print(f"VAPID_PRIVATE_KEY={b64(private)}")
print(f"VAPID_PUBLIC_KEY={b64(public)}")
