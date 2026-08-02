"""Pure RFC-6238 TOTP (spec 48) — stdlib only, unit-tested against the RFC
vectors. SHA-1/30s/6-digit, the profile every authenticator app ships with."""

import base64
import hashlib
import hmac
import secrets
import struct
import urllib.parse

TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
# Steps of clock drift accepted either side of "now" — one step (±30s) is the
# conventional tolerance; more weakens the code meaningfully.
TOTP_DRIFT_STEPS = 1


def generate_secret() -> str:
    """New random base32 secret (160 bits, the RFC-4226 recommended size)."""
    return base64.b32encode(secrets.token_bytes(20)).decode()


def code_at(secret: str, timestamp: int) -> str:
    """The 6-digit code for the step containing `timestamp` (epoch seconds)."""
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    counter = struct.pack(">Q", timestamp // TOTP_STEP_SECONDS)
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def verify_code(secret: str, code: str, timestamp: int) -> bool:
    """Constant-time compare across the accepted drift window."""
    normalized = code.strip().replace(" ", "")
    ok = False
    for step in range(-TOTP_DRIFT_STEPS, TOTP_DRIFT_STEPS + 1):
        expected = code_at(secret, timestamp + step * TOTP_STEP_SECONDS)
        # no early exit — uniform work regardless of which step matches
        ok = hmac.compare_digest(expected, normalized) or ok
    return ok


def provisioning_uri(secret: str, account: str, issuer: str = "Radd") -> str:
    """otpauth:// URI authenticator apps import (shown as text — no QR dep)."""
    label = urllib.parse.quote(f"{issuer}:{account}")
    query = urllib.parse.urlencode(
        {"secret": secret, "issuer": issuer, "algorithm": "SHA1",
         "digits": TOTP_DIGITS, "period": TOTP_STEP_SECONDS}
    )
    return f"otpauth://totp/{label}?{query}"
