"""At-rest encryption for row-level secrets (RADD-1086).

The key is DERIVED from the instance's backup key (HMAC-SHA256 with a fixed
domain tag) rather than being a second file: the operator already has exactly
one key to protect and carry through a restore, and a derived key keeps that
story true while guaranteeing backup ciphertext and row ciphertext never share
key material. Values are stored as `enc1:<b64(nonce || AES-256-GCM box)>`;
anything without the prefix is legacy plaintext and passes through `decrypt`
unchanged, which is what makes adoption lazy: a row's secret takes its encrypted
form (`adopt`) on its next save, and each owner's startup hook re-encrypts the
stragglers whenever the key is available.
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

#: What an update payload's secret field carries to mean "keep what is stored"
#: (RADD-1467, one spelling for the mail dialogs' convention). A redacted read never
#: hands a secret back, so a form that round-trips one sends this; removing a secret
#: is a separate, explicit operation (settings' `clear_value`).
KEEP_SECRET = ""


def keeps_secret(value: object) -> bool:
    """Whether an update's secret field asks to keep the stored one: absent, null or `KEEP_SECRET`."""
    return value is None or value == KEEP_SECRET

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


def seal(plain: str) -> str:
    """`encrypt`, except that "" stays "" — a row answers "is one set?" with
    `bool(stored)`, which an encrypted empty string would falsely answer yes."""
    return encrypt(plain) if plain else ""


def adopt(stored: str) -> str:
    """A stored secret in its encrypted form: legacy plaintext is encrypted,
    ciphertext and "" come back unchanged (the same object, so an ORM
    attribute assigned its own value stays clean)."""
    return stored if not stored or is_encrypted(stored) else encrypt(stored)


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
