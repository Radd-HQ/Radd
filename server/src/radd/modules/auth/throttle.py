"""Bounded login admission for the documented single-web-process deployment."""

import hashlib
import logging
import math
import time
from collections import deque

from fastapi import HTTPException, Request

from radd.config import settings

logger = logging.getLogger(__name__)


class LoginThrottle:
    def __init__(self) -> None:
        self.buckets: dict[str, deque[float]] = {}

    def check(self, account: str, address: str, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        cutoff = now - settings.auth_login_window_seconds
        # Bound both retained identities and per-identity attempt history.
        for key, entries in list(self.buckets.items()):
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if not entries:
                del self.buckets[key]
        identity = hashlib.sha256(account.strip().casefold().encode()).hexdigest()
        keys = (
            ("account:" + identity, settings.auth_login_account_attempts),
            ("ip:" + address, settings.auth_login_ip_attempts),
        )
        for key, limit in keys:
            entries = self.buckets.get(key, ())
            if len(entries) >= limit:
                self._refuse(max(1, math.ceil(entries[0] - cutoff)))
        if (
            len(self.buckets) + sum(k not in self.buckets for k, _ in keys)
            > settings.auth_login_bucket_limit
        ):
            self._refuse(math.ceil(settings.auth_login_window_seconds))
        for key, _ in keys:
            self.buckets.setdefault(key, deque()).append(now)

    @staticmethod
    def _refuse(retry_after: int) -> None:
        logger.warning("login throttled; retry after %s seconds", retry_after)
        raise HTTPException(
            429,
            "Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


login_throttle = LoginThrottle()


def check_login_attempt(request: Request, account: str) -> None:
    # Use the application's trusted-proxy resolver, never raw forwarded headers.
    address = getattr(request.state, "client_ip", None)
    login_throttle.check(account, address or (request.client.host if request.client else "unknown"))
