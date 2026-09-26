"""The HTTPS ingest source (RADD-953): transport and authentication only."""

from __future__ import annotations

import hashlib
import hmac

#: The header prefix Cloudflare's Worker sends: `sha256=<hex>`.
SIGNATURE_PREFIX = "sha256="


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time check of the hex HMAC-SHA256 over the EXACT raw body. An EMPTY
    secret rejects everything (fail closed); `compare_digest` because the signature
    is attacker-supplied and an early exit leaks the forged prefix."""
    if not secret or not signature:
        return False
    provided = signature[len(SIGNATURE_PREFIX) :] if signature.startswith(
        SIGNATURE_PREFIX
    ) else signature
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided.strip().lower(), expected)
