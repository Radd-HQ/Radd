"""Mail-loop guards (RADD-957).

The failure this prevents: Radd mails a participant, their out-of-office replies
to `help@`, that opens a ticket, the ticket mails the participants, one of whom
is also away. It runs at the speed of two mail servers and looks like ordinary
traffic while it does.

Three guards, because each alone has a hole:

  Auto-Submitted   RFC 3834's own marker. Every well-behaved autoresponder sets
                   it — and the badly-behaved ones are the majority.
  self-addressed   the direct loop, and the cheapest check there is.
  rate limit       what actually catches the ones setting no header at all.

`Precedence: bulk`/`list` and `List-Id` are deliberately NOT triggers. Plenty of
legitimate ticket traffic arrives from list addresses, and silently dropping a
customer's mail is worse than the loop it would prevent.

**Every drop is an acceptance, never a rejection.** The caller answers 202: the
message was received and deliberately discarded. Bouncing at a loop puts another
message into the loop.
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
    """Why a message was dropped, or that it was not. `reason` is logged — a
    silent drop and a bug are indistinguishable from the outside."""

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
    """The pure decision. `own_addresses` are every address Radd sends AS —
    lower-cased, from the sender rows, so an instance that changes its From does
    not need a code change."""
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
    """Per-sender sliding window, in process memory.

    In memory on purpose. A loop is a burst measured in seconds, every web
    replica is behind the same endpoint, and a per-replica cap of 20 still stops
    it — while a database-backed counter would put a write on the hot path of
    the endpoint most likely to be under a flood. It is a circuit breaker, not
    an accounting record.
    """

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
        # Bound the map: a flood from thousands of forged senders must not become
        # a memory leak. Dropping the coldest entry only loses a count nobody was
        # near the limit on.
        if len(self._seen) > 10_000:
            coldest = min(self._seen, key=lambda key: self._seen[key][-1])
            self._seen.pop(coldest, None)
        return True


#: The process-wide limiter the ingest endpoint consults.
limiter = RateLimiter()
