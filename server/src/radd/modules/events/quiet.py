"""Scopes that mark emitted events: `quiet()` → `silent`; `automated()` → automation-caused.

A bulk import emits an event per row. Consumers that act OUTSIDE the instance (notify,
webhooks, automations, realtime) skip silent rows; internal-state consumers (search, history)
still take them. A scope, not a flag, because the emits happen deep in services that must not
know who is calling; a ContextVar survives `await` and is copied into tasks. Preferred over
moving cursors past an import, which would swallow other people's concurrent work.
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
    """Which automation's run wrote an event, and how deep in a chain (RADD-1315).

    `depth` is 1 for a run a person's event started, else the trigger's depth + 1. An opted-in
    trigger fires only below `automation_max_chain_depth`, and never on its OWN automation's
    events — what keeps chaining from looping. `rule_id` is None only for the engine's own
    reports (`run_failed`)."""

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
    """Mark events emitted here as automation-caused — THE LOOP GUARD (spec 116). Causation
    lives on the event because an action may run AS a real person. The cause (RADD-1315) is
    the explicit one, else the enclosing run's (`run_cause`), else an anonymous depth-1 one."""
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
    """Mark the REST OF THIS TASK as automation-caused, with no scope to leave — for a
    request authenticated with an engine-minted key (RADD-1314), whose cause it carries.
    FastAPI awaits dependencies in the request's own task, so the mark dies with the request.
    Never call it from code that outlives one request: a worker loop would mark every later event."""
    _cause.set(cause or AutomationCause())
