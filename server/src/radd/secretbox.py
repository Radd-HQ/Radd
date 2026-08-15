"""At-rest encryption for row-level secrets (RADD-1086).

The key is DERIVED from the instance's backup key (HMAC-SHA256 with a fixed
domain tag) rather than being a second file: the operator already has exactly
one key to protect and carry through a restore, and a derived key keeps that
story true while guaranteeing backup ciphertext and row ciphertext never share
key material. Values are stored as `enc1:<b64(nonce || AES-256-GCM box)>`;
anything without the prefix is legacy plaintext and passes through `decrypt`
unchanged, which is what makes adoption lazy — the webhooks startup hook
re-encrypts stragglers whenever the key is available.
"""

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from radd.backup import crypto as backup_crypto

_PREFIX = "enc1:"
_DOMAIN = b"radd-secretbox-v1"
_NONCE_BYTES = 12

_cached_key: bytes | None = None


class SecretBoxError(Exception):
    """The key is unavailable or the ciphertext does not authenticate."""


def _key() -> bytes:
    global _cached_key
    if _cached_key is None:
        try:
            material = backup_crypto.load_key().material
        except backup_crypto.BackupKeyError as exc:
            raise SecretBoxError(str(exc)) from exc
        _cached_key = hmac.new(material, _DOMAIN, hashlib.sha256).digest()
    return _cached_key


def reset_key_cache() -> None:
    """Tests swap settings.backup_key_file; the cache must not outlive that."""
    global _cached_key
    _cached_key = None


def is_encrypted(value: str) -> bool:
    return value.startswith(_PREFIX)


def encrypt(plain: str) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    box = AESGCM(_key()).encrypt(nonce, plain.encode(), None)
    return _PREFIX + base64.b64encode(nonce + box).decode()


def decrypt(stored: str) -> str:
    """Encrypted values decrypt; anything else is legacy plaintext, returned
    as-is — the passthrough is what lets rows adopt encryption lazily."""
    if not is_encrypted(stored):
        return stored
    try:
        raw = base64.b64decode(stored.removeprefix(_PREFIX), validate=True)
        nonce, box = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
        return AESGCM(_key()).decrypt(nonce, box, None).decode()
    except (ValueError, InvalidTag) as exc:
        raise SecretBoxError("stored secret does not authenticate (wrong key or tamper)") from exc
