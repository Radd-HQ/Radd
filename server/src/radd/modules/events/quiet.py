"""Quiet scope — mark emitted events `silent` so outward-acting consumers skip them.

A bulk importer writes tens of thousands of items, and every one of them emits an
event. Without this, notify, webhooks and the automations engine each fan that
out: thousands of notification rows and emails, thousands of HTTP deliveries, and
thousands of rule executions — all for work that happened years ago in another
system. `quiet()` marks everything emitted inside it, and the consumers that reach
OUTSIDE the instance skip those rows.

Consumers that build INTERNAL state still consume them, deliberately: the search
index (an imported issue must be findable) and the activity/history feed (an
imported issue must have history). The distinction is "does this consumer tell
someone", not "does this consumer care".

This is a scope rather than a flag on every call site because the emits happen
deep inside the items/comments/worklog services, which must stay ignorant of who
is calling them. A ContextVar survives `await` and is copied into tasks created
inside the scope, so one `with` around a background import run covers every write
it makes.

Preferred over advancing each consumer's cursor past the import's event range:
that would also swallow unrelated activity by other people committed during the
same window.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_quiet: ContextVar[bool] = ContextVar("radd_events_quiet", default=False)


def is_quiet() -> bool:
    """Whether the caller is running inside a `quiet()` scope."""
    return _quiet.get()


@contextmanager
def quiet(enabled: bool = True) -> Iterator[None]:
    """Mark every event emitted in this scope `silent`.

    `enabled=False` is a no-op, so a caller can pass a user-facing toggle straight
    through without branching:

        with events.quiet(plan.quiet_import):
            ...
    """
    token = _quiet.set(enabled)
    try:
        yield
    finally:
        _quiet.reset(token)


# --- automation causation (spec 116) -----------------------------------------

_automated: ContextVar[bool] = ContextVar("radd_events_automated", default=False)


def is_automated() -> bool:
    """Whether the caller is running inside an `automated()` scope."""
    return _automated.get()


@contextmanager
def automated(enabled: bool = True) -> Iterator[None]:
    """Mark every event emitted in this scope as automation-caused.

    THE LOOP GUARD, since "act as" (spec 116). Before it, the engine recognised
    its own effects by their ACTOR: every engine mutation ran as SYSTEM_ACTOR_ID
    and `should_process` skipped those. An action that can run as a real person
    ends that — its events are indistinguishable from that person's own — so
    causation moved onto the event and identity was left to mean identity.

    A scope rather than a parameter for the same reason `quiet` is one: the emits
    happen deep inside items/comments/worklogs, which must stay ignorant of who
    is calling them, and a ContextVar survives `await`.
    """
    token = _automated.set(enabled)
    try:
        yield
    finally:
        _automated.reset(token)
