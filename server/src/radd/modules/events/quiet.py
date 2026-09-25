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

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

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


# --- automation causation (spec 116; chain depth RADD-1315) -------------------


@dataclass(frozen=True)
class AutomationCause:
    """Why an event is automation-caused: WHICH automation's run wrote it, and how
    deep in a chain that run sits (RADD-1315).

    `depth` is 1 for a run started by a person's (or an integration's) event, and
    one more than the triggering event's depth for a run started by another
    automation's change. A trigger that opted in to other automations' changes
    fires only below `automation_max_chain_depth`, and never on an event its OWN
    automation caused — that is what keeps chaining from looping.

    `rule_id` is None only when the engine reports on itself (`run_failed`).
    """

    rule_id: uuid.UUID | None = None
    depth: int = 1

    def as_json(self) -> dict[str, Any]:
        return {"rule_id": str(self.rule_id) if self.rule_id else None, "depth": self.depth}

    @classmethod
    def from_json(cls, raw: Mapping[str, Any] | None) -> "AutomationCause":
        raw = raw or {}
        rule = raw.get("rule_id")
        try:
            depth = max(1, int(raw.get("depth") or 1))
        except (TypeError, ValueError):
            depth = 1
        return cls(rule_id=uuid.UUID(str(rule)) if rule else None, depth=depth)


#: The cause of whatever is being emitted RIGHT NOW (inside `automated()`).
_cause: ContextVar[AutomationCause | None] = ContextVar("radd_events_automation_cause", default=None)
#: The cause the current automation RUN will stamp (set by the engine around a
#: walk, entered by `automated()` inside it). Separate from `_cause` because a
#: run also READS and emits nothing automated until an action applies.
_run_cause: ContextVar[AutomationCause | None] = ContextVar("radd_events_run_cause", default=None)


def is_automated() -> bool:
    """Whether the caller is running inside an `automated()` scope."""
    return _cause.get() is not None


def current_cause() -> AutomationCause | None:
    """The cause events emitted here would carry — None outside `automated()`."""
    return _cause.get()


@contextmanager
def automated(enabled: bool = True, cause: AutomationCause | None = None) -> Iterator[None]:
    """Mark every event emitted in this scope as automation-caused.

    THE LOOP GUARD, since "act as" (spec 116). Before it, the engine recognised
    its own effects by their ACTOR: every engine mutation ran as SYSTEM_ACTOR_ID
    and `should_process` skipped those. An action that can run as a real person
    ends that — its events are indistinguishable from that person's own — so
    causation moved onto the event and identity was left to mean identity.

    The cause (RADD-1315) is the explicit one, else the enclosing RUN's
    (`run_cause`), else an anonymous depth-1 cause.

    A scope rather than a parameter for the same reason `quiet` is one: the emits
    happen deep inside items/comments/worklogs, which must stay ignorant of who
    is calling them, and a ContextVar survives `await`.
    """
    value = (cause or _run_cause.get() or AutomationCause()) if enabled else None
    token = _cause.set(value)
    try:
        yield
    finally:
        _cause.reset(token)


@contextmanager
def run_cause(cause: AutomationCause) -> Iterator[None]:
    """The engine's scope around one automation RUN: every `automated()` inside
    it stamps this cause, so the run's writes say which rule made them and at
    what chain depth (RADD-1315)."""
    token = _run_cause.set(cause)
    try:
        yield
    finally:
        _run_cause.reset(token)


def enter_automated(cause: AutomationCause | None = None) -> None:
    """Mark the REST OF THIS TASK as automation-caused, with no scope to leave.

    For a request authenticated with a key the automation engine minted
    (RADD-1314): the auth dependency calls this, and FastAPI awaits dependencies
    in the request's own task, so the mark covers the endpoint and dies with the
    request. The key carries the minting run's cause, so a script's writes chain
    exactly like a built-in action's (RADD-1315). Never call it from code that
    outlives one request — a worker loop would mark every later event."""
    _cause.set(cause or AutomationCause())
