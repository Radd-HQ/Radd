"""Integration sockets — typed plugin-to-plugin implementation points (§4a).

A socket is a named interface one plugin *provides* and another *consumes*: a
plugin registers `IntegrationSpec(socket, name, impl)` on its manifest, and a
consumer resolves the active one via a settings key. This is the uniform shape
behind "S3 as a plugin" (StorageBackend), "Celery as a plugin" (TaskBackend),
notifiers, connectors, AI/VCS providers, and the upload filter pipeline.

Per docs/plugin-platform.md §13 most of these are **[seam]s**: the interface is
defined now; a concrete second provider arrives when the first consuming plugin is
actually built. `StorageBackend` and `TaskBackend` already have real providers.
"""

from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


from .registry import registries


class Socket(StrEnum):
    STORAGE_BACKEND = "storage_backend"  # filesystem | s3 (attachments)
    STORAGE_ROUTING_RULE = "storage_routing_rule"  # user_choice | cidr | llm (spec 102)
    TASK_BACKEND = "task_backend"  # localloop (default) | celery
    NON_WORKING_DAYS = "non_working_days"  # calendar dates nobody works (RADD-1031)
    TRANSITION_CHECK = "transition_check"  # a workflow transition-rule check (RADD-1383)


# --- interface definitions (the seam contracts) ---


@runtime_checkable
class StorageBackend(Protocol):
    """Per-host blob client (spec 102). The registered impl is a CLASS taking a
    StorageHost row; instances deal in `storage_name` (opaque uuid) keys. The
    attachments module resolves one per host via `client_for` — a plugin host
    type is one more IntegrationSpec."""

    async def save(self, storage_name: str, source: Any, *, size: int, content_type: str) -> None: ...
    async def remove(self, storage_name: str) -> None: ...
    async def read(self, storage_name: str) -> bytes: ...
    async def response(self, attachment: Any) -> Any: ...


@runtime_checkable
class TaskBackend(Protocol):
    """Background-work dispatch (§6). `localloop` (the builtin `PeriodicLoop`) is the
    default; a `celery` plugin provides an alternative."""

    def schedule(self, name: str, run: Any, interval: Any, gate: Any) -> Any: ...
    def enqueue(self, name: str, run: Any) -> Any: ...


@runtime_checkable
class Notifier(Protocol):
    async def notify(self, target: str, message: dict[str, Any]) -> None: ...


@runtime_checkable
class RoutingRule(Protocol):
    """One storage routing-rule TYPE (spec 102): evaluates an upload's context
    against an admin-authored config and answers with a host id, or None to
    fall through to the next rule in the chain. `config_model` is the pydantic
    class validating the rule's stored JSON config. A plugin rule type is one
    IntegrationSpec on this socket."""

    config_model: Any

    async def evaluate(self, session: Any, ctx: Any, config: Any) -> Any: ...


@runtime_checkable
class NonWorkingDaysProvider(Protocol):
    """Calendar dates on which the INSTANCE does not work (RADD-1031).

    Mechanism only: the kernel knows there is such a thing as a day nobody
    works, and nothing about why. `leave` answers with its studio holidays; a
    plugin holding a regional calendar answers alongside it — every provider on
    the socket is asked and the answers UNION, because a date is non-working if
    anyone's calendar says so.

    The subject is the instance, not a person: an SLA clock is attached to an
    item, so there is no user whose personal absence could pause it. Providers
    must therefore answer with dates that stop work for everybody, never with
    one person's leave.

    Answers are advisory and time-boxed to the [start, end] window the consumer
    asks for, so a provider never has to enumerate a calendar it cannot bound.
    """

    async def non_working_dates(self, session: Any, start: date, end: date) -> set[date]: ...


@runtime_checkable
class TransitionCheckProvider(Protocol):
    """One CHECK a workflow transition rule may name (RADD-1383).

    Mechanism only: the kernel knows a transition row carries rules
    `[{check, params}]` and that some checks belong to plugins. `workflow`
    evaluates its own (field conditions, resolved threads, a release) and asks
    this socket for every other key; `approvals` answers `require_approval`.
    The provider owns the check end to end, so workflow never learns it exists:

    * `check` — the rule's `check` key, unique across providers (register the
      IntegrationSpec under the same name);
    * `sort_last` — its failure follows workflow's own: a gate someone else
      clears reads after the data the mover can fix;
    * `validate(session, params)` — the WRITE path: return the params to store
      (normalized, display names snapshotted server-side) or raise the
      `ConflictError` (409) the rule editor shows;
    * `prepare(session, item)` — the per-item data `failure` needs, fetched once
      per evaluation so a list of targets costs one query, not one per target;
    * `failure(params, prepared, to_state_id)` — pure: None when the rule
      passes, else the human sentence the mover sees;
    * `moved(session, item_id, to_state_id)` — told after every successful
      state change, whatever governed it (an approval is spent by the move it
      unlocked).

    A stored rule whose provider is gone — the plugin disabled or uninstalled —
    FAILS CLOSED in workflow: an admin configured that gate, and switching a
    plugin off must not quietly open it.
    """

    check: str
    sort_last: bool

    async def validate(self, session: Any, params: dict[str, Any]) -> dict[str, Any]: ...
    async def prepare(self, session: Any, item: Any) -> Any: ...
    def failure(
        self, params: Mapping[str, Any], prepared: Any, to_state_id: str | None
    ) -> str | None: ...
    async def moved(self, session: Any, item_id: Any, to_state_id: Any) -> None: ...


@runtime_checkable
class AttachmentFilter(Protocol):
    """Synchronous, ordered, *vetoing* hook every upload passes through (§13
    interceptor). Raise to reject; return (optionally transformed) bytes to accept."""

    async def check(self, filename: str, content: bytes) -> bytes: ...


# --- resolution helpers (over the kernel integrations registry) ---


def providers(socket: Socket | str) -> dict[str, Any]:
    """All registered providers of a socket → {name: impl}."""
    return {n: ig.impl for n, ig in registries.providers(str(socket)).items()}


def provider(socket: Socket | str, name: str) -> Any:
    ig = registries.integration(str(socket), name)
    return ig.impl if ig else None


