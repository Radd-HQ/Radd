"""A per-address cap on error reports: a tab in a render loop must not fill the log.

In-process and approximate on purpose. It protects the log, not an account, so
losing its memory on restart (or splitting it across processes) costs nothing."""

import time
from collections import deque

from radd.config import settings

_WINDOW_SECONDS = 60.0
#: Addresses remembered at once; past it new addresses are refused until old ones age out.
_MAX_ADDRESSES = 5000

_seen: dict[str, deque[float]] = {}


def admit(address: str, *, now: float | None = None) -> bool:
    """Record one report from `address`; False when it is over its minute's allowance."""
    moment = time.monotonic() if now is None else now
    cutoff = moment - _WINDOW_SECONDS
    for key, entries in list(_seen.items()):
        while entries and entries[0] <= cutoff:
            entries.popleft()
        if not entries:
            del _seen[key]
    entries = _seen.get(address)
    if entries is None:
        if len(_seen) >= _MAX_ADDRESSES:
            return False
        entries = _seen[address] = deque()
    if len(entries) >= settings.client_error_reports_per_minute:
        return False
    entries.append(moment)
    return True


def reset() -> None:
    _seen.clear()
