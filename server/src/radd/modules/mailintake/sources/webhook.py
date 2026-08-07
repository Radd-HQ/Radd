"""The HTTPS ingest source (RADD-953).

Mail reaches this deployment over HTTPS because it cannot reach it any other
way: the ISP drops port 25 in both directions, so Cloudflare Email Routing
accepts the message and a Worker posts it here. The Worker is deliberately thin —
it parses nothing and decides nothing — which is what lets a Gmail push adapter
and an IMAP poller feed the very same `intake` core later.

This module is transport and authentication. Everything else is `intake`'s.
"""

from __future__ import annotations

import hashlib
import hmac

#: The header prefix Cloudflare's Worker sends: `sha256=<hex>`.
SIGNATURE_PREFIX = "sha256="


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Constant-time check of the hex HMAC-SHA256 over the EXACT raw body.

    Same shape as `forgejo.service.verify_signature`, including the property
    that matters most: **an empty secret rejects everything.** A misconfigured
    instance must fail closed — the alternative is an unauthenticated,
    internet-reachable endpoint that creates issues, which is the worst possible
    way to discover a missing environment variable.

    The comparison is `compare_digest` rather than `==` because the signature is
    attacker-supplied and a byte-by-byte early exit leaks how much of a forged
    prefix was correct.
    """
    if not secret or not signature:
        return False
    provided = signature[len(SIGNATURE_PREFIX) :] if signature.startswith(
        SIGNATURE_PREFIX
    ) else signature
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided.strip().lower(), expected)
