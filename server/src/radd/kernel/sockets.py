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

from datetime import date
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


from .registry import registries


class Socket(StrEnum):
    STORAGE_BACKEND = "storage_backend"  # filesystem | s3 (attachments)
    STORAGE_ROUTING_RULE = "storage_routing_rule"  # user_choice | cidr | llm (spec 102)
    TASK_BACKEND = "task_backend"  # localloop (default) | celery
    NOTIFIER = "notifier"  # google_chat | email | slack
    CONNECTOR = "connector"  # inbound webhook parsers (gitlab/forgejo/alertmanager)
    AI_PROVIDER = "ai_provider"  # openai | anthropic
    VCS_PROVIDER = "vcs_provider"  # gitlab | forgejo
    ATTACHMENT_FILTER = "attachment_filter"  # veto/transform an upload (interceptor)
    NON_WORKING_DAYS = "non_working_days"  # calendar dates nobody works (RADD-1031)


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

    def schedule(self, name: str, run: Any, interval: Any, gate: Any) -> None: ...
    def enqueue(self, name: str, run: Any) -> None: ...
    def run_workers(self) -> None: ...


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


def active_provider(socket: Socket | str, name: str) -> Any:
    """The provider selected by name (usually a settings value) — the active one."""
    return provider(socket, name)
