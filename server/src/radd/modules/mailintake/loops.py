"""Mail-loop guards (RADD-957): Radd mails someone, their autoresponder writes
back to `help@`, which opens a ticket that mails them again.

  Auto-Submitted   RFC 3834's marker — set by well-behaved autoresponders only
  self-addressed   the direct loop, and the cheapest check
  rate limit       catches the ones setting no header at all

`Precedence: bulk`/`List-Id` are NOT triggers: legitimate ticket mail arrives
from lists. Every drop is an ACCEPTANCE (202) — bouncing feeds the loop.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from email.utils import parseaddr

#: Messages one envelope sender may have accepted per window before the rest are
#: dropped. Generous enough that a person forwarding a thread is unaffected, low
#: enough that a runaway autoresponder is stopped within seconds.
RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW_SECONDS = 300.0

#: `Auto-Submitted:` values that mean "a machine sent this". RFC 3834 defines
#: `no` as the only value meaning a human did, so anything else counts — matching
#: on the two known strings would miss `auto-notified` and every vendor variant.
AUTO_SUBMITTED_HUMAN = "no"


@dataclass(frozen=True)
class LoopVerdict:
    """Why a message was dropped, or that it was not. `reason` is logged."""

    drop: bool
    reason: str = ""


def _addr(value: str | None) -> str:
    return parseaddr(value or "")[1].strip().lower()


def check(
    *,
    auto_submitted: str | None,
    from_header: str | None,
    envelope_from: str | None,
    own_addresses: set[str],
) -> LoopVerdict:
    """The pure decision. `own_addresses`: every address Radd sends AS, lower-cased
    (`registry.own_addresses`)."""
    marker = (auto_submitted or "").strip().lower()
    if marker and marker != AUTO_SUBMITTED_HUMAN:
        return LoopVerdict(True, f"Auto-Submitted: {marker}")

    sender = _addr(from_header)
    if sender and sender in own_addresses:
        return LoopVerdict(True, f"From is our own address ({sender})")
    envelope = _addr(envelope_from)
    if envelope and envelope in own_addresses:
        return LoopVerdict(True, f"envelope sender is our own address ({envelope})")

    return LoopVerdict(False)


class RateLimiter:
    """Per-sender sliding window, in process memory on purpose: a loop is a burst
    of seconds, a per-replica cap still stops it, and a DB counter would put a
    write on the hot path of the endpoint most likely to be flooded."""

    def __init__(
        self, *, limit: int = RATE_LIMIT_MAX, window: float = RATE_LIMIT_WINDOW_SECONDS
    ) -> None:
        self._limit = limit
        self._window = window
        self._seen: dict[str, deque[float]] = {}

    def allow(self, sender: str, *, now: float | None = None) -> bool:
        """True if this sender may have another message accepted."""
        address = _addr(sender)
        if not address:
            return True  # a bounce (empty envelope) is rate-limited by the caller's own rules
        moment = time.monotonic() if now is None else now
        hits = self._seen.setdefault(address, deque())
        cutoff = moment - self._window
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(moment)
        # Bound the map against forged-sender floods; the coldest entry was not
        # near the limit.
        if len(self._seen) > 10_000:
            coldest = min(self._seen, key=lambda key: self._seen[key][-1])
            self._seen.pop(coldest, None)
        return True


#: The process-wide limiter the ingest endpoint consults.
limiter = RateLimiter()

