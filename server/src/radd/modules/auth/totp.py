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


# --- recovery codes (RADD-677) -------------------------------------------------

RECOVERY_CODE_COUNT = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i lookalikes
_RECOVERY_GROUP = 5


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """`xxxxx-xxxxx` over a 31-char alphabet — ~49.6 bits each, unguessable
    online and cheap to type from a printout."""
    return [
        "-".join(
            "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_GROUP))
            for _ in range(2)
        )
        for _ in range(count)
    ]


def normalize_recovery_code(code: str) -> str:
    return code.strip().lower().replace(" ", "").replace("-", "")


def hash_recovery_code(code: str) -> str:
    """SHA-256 of the normalized form. High-entropy input is what makes a fast
    hash correct here; a low-entropy secret would need argon2 instead."""
    return hashlib.sha256(normalize_recovery_code(code).encode()).hexdigest()


def looks_like_recovery_code(code: str) -> bool:
    """A 6-digit string is a TOTP code; anything longer with letters is a
    recovery attempt — used to keep the login error paths uniform."""
    normalized = normalize_recovery_code(code)
    return len(normalized) == 2 * _RECOVERY_GROUP and not normalized.isdigit()
