"""Password and token primitives. Raw tokens are never stored — sha256 hex only."""

import hashlib
import secrets
from datetime import UTC, datetime

from pwdlib import PasswordHash

from .types import PAT_PREFIX

_hasher = PasswordHash.recommended()  # argon2id
# Verified against when the user doesn't exist, so login timing stays uniform.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-work check: hashes against a dummy when the account has no password."""
    ok = _hasher.verify(password, password_hash or _DUMMY_HASH)
    return ok and password_hash is not None


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_api_token() -> str:
    return PAT_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def utcnow() -> datetime:
    """Naive UTC, matching the timezone-naive DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)
