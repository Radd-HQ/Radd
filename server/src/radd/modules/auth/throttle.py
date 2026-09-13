"""Bounded admission for the documented single-web-process deployment.

Two throttles over one sliding window: `LoginThrottle` (per-account + per-IP,
the password login routes) and `WriteThrottle` (per-account, issue and comment
creation — spec 121 §9, RADD-1148). Both keep their counters in this process
only; multiple workers or replicas need a shared admission store or ingress
controls, as `docs/deploy.md` says.
"""

import hashlib
import logging
import math
import time
import uuid
from collections import deque
from enum import StrEnum

from fastapi import HTTPException, Request

from radd.config import settings

from .models import User
from .principals import is_instance_admin

logger = logging.getLogger(__name__)

#: The automation engine's actor (`automations.types.SYSTEM_ACTOR_ID`). auth
#: loads before automations, so the uuid is a literal here — the notify idiom —
#: and `test_write_throttle.py` pins the two together so it cannot drift.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000a70a70")


class WriteBucket(StrEnum):
    """A throttled write, with its per-window limit read from settings."""

    ITEM_CREATE = "item.create"
    COMMENT_CREATE = "comment.create"

    @property
    def limit(self) -> int:
        return {
            WriteBucket.ITEM_CREATE: settings.item_creates_per_window,
            WriteBucket.COMMENT_CREATE: settings.comments_per_window,
        }[self]


class _SlidingWindow:
    """Per-key timestamps inside one window, bounded in keys and in history."""

    def __init__(self) -> None:
        self.buckets: dict[str, deque[float]] = {}

    def admit(
        self,
        keys: tuple[tuple[str, int], ...],
        now: float,
        *,
        window_seconds: float,
        bucket_limit: int,
    ) -> int | None:
        """Record one attempt under every key, or return the seconds to wait.

        Nothing is recorded when any key is over its limit or the bucket table
        would overflow, so a refused attempt never extends the caller's wait.
        The limits are parameters, not construction state, so a settings change
        takes effect on the next call.
        """
        cutoff = now - window_seconds
        # Bound both retained identities and per-identity attempt history.
        for key, entries in list(self.buckets.items()):
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if not entries:
                del self.buckets[key]
        for key, limit in keys:
            entries = self.buckets.get(key, ())
            if len(entries) >= limit:
                return max(1, math.ceil(entries[0] - cutoff))
        if len(self.buckets) + sum(k not in self.buckets for k, _ in keys) > bucket_limit:
            return math.ceil(window_seconds)
        for key, _ in keys:
            self.buckets.setdefault(key, deque()).append(now)
        return None


def _refuse(retry_after: int, what: str, detail: str) -> None:
    logger.warning("%s throttled; retry after %s seconds", what, retry_after)
    raise HTTPException(429, detail, headers={"Retry-After": str(retry_after)})


class LoginThrottle:
    def __init__(self) -> None:
        self._window = _SlidingWindow()

    @property
    def buckets(self) -> dict[str, deque[float]]:
        return self._window.buckets

    def check(self, account: str, address: str, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        identity = hashlib.sha256(account.strip().casefold().encode()).hexdigest()
        keys = (
            ("account:" + identity, settings.auth_login_account_attempts),
            ("ip:" + address, settings.auth_login_ip_attempts),
        )
        retry_after = self._window.admit(
            keys,
            now,
            window_seconds=settings.auth_login_window_seconds,
            bucket_limit=settings.auth_login_bucket_limit,
        )
        if retry_after is not None:
            _refuse(retry_after, "login", "Too many sign-in attempts. Try again later.")


class WriteThrottle:
    """Per-(bucket, account) admission for the creation routes."""

    def __init__(self) -> None:
        self._window = _SlidingWindow()

    @property
    def buckets(self) -> dict[str, deque[float]]:
        return self._window.buckets

    def check(self, bucket: WriteBucket, user_id: uuid.UUID, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        keys = ((f"{bucket}:{user_id}", bucket.limit),)
        retry_after = self._window.admit(
            keys,
            now,
            window_seconds=settings.write_window_seconds,
            bucket_limit=settings.write_throttle_bucket_limit,
        )
        if retry_after is not None:
            _refuse(retry_after, bucket, "Too many writes. Try again later.")


login_throttle = LoginThrottle()
write_throttle = WriteThrottle()


def check_login_attempt(request: Request, account: str) -> None:
    # Use the application's trusted-proxy resolver, never raw forwarded headers.
    address = getattr(request.state, "client_ip", None)
    login_throttle.check(account, address or (request.client.host if request.client else "unknown"))


def check_write(user: User, bucket: WriteBucket) -> None:
    """Admit one creation by `user`, or raise 429 with `Retry-After`.

    Instance admins and the automation engine's actor are exempt: the throttle
    exists for open sign-up on a public instance, and neither of those is a
    stranger.
    """
    if user.id == SYSTEM_ACTOR_ID or is_instance_admin(user):
        return
    write_throttle.check(bucket, user.id)
