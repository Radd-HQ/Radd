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

from collections.abc import Mapping, Sequence
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
    SEARCH_DOCUMENTS = "search_documents"  # non-item hits search shows (RADD-1384)
    SEMANTIC_CANDIDATES = "semantic_candidates"  # meaning-ranked ids for a query (RADD-1384)
    # RADD-1385: what notify learns from optional plugins instead of importing them.
    NOTIFICATION_SUBJECT = "notification_subject"  # a non-item thing notifications are about (pages)
    NOTIFICATION_AUDIENCE = "notification_audience"  # more people following an item (participants)
    MAIL_TRANSPORT = "mail_transport"  # carries a notification email (mailintake)


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
class SearchDocumentSource(Protocol):
    """A corpus of DOCUMENTS search shows beside issues (RADD-1384).

    Mechanism only: `search` knows there are non-item hits it can rank, fuse
    with semantic candidates and shape into deflection and Ask-mode answers;
    `pages` answers with wiki pages. The provider owns its ACL end to end, so
    search never learns what a space or a page restriction is:

    * `entity_type` — the id space its hits live in; it is what the
      SEMANTIC_CANDIDATES socket is asked for (register the spec under it);
    * `search(session, actor, q, limit=)` — the full-text ranking, best-first,
      of the documents `actor` may read, scoped BEFORE the limit so unreadable
      hits never eat the budget;
    * `resolve(session, actor, ids)` — the live, readable subset of `ids`
      through the same gate, in any order: how a semantic-only candidate
      becomes a hit.

    Both answer `search.sources.DocumentHit`s — the consumer's shape, which the
    provider imports (a provider depends on search, never the reverse). No
    provider registered means no documents: deflection and Ask mode answer with
    issues alone, and nothing errors.
    """

    entity_type: str

    async def search(self, session: Any, actor: Any, q: str, *, limit: int) -> list[Any]: ...
    async def resolve(self, session: Any, actor: Any, ids: Sequence[Any]) -> list[Any]: ...


@runtime_checkable
class SemanticCandidateSource(Protocol):
    """Meaning-ranked candidates for a query (RADD-1384); `ai` answers from its
    embeddings.

    * `enabled(session)` — whether it can answer RIGHT NOW (switched on,
      configured, its store reachable); cheap-first, since every hybrid search
      asks;
    * `candidates(session, entity_type, q, limit=, project_ids=)` — `(id, cosine
      distance)` nearest-first for one entity type, `[]` for a type it does not
      embed. Item candidates are pre-filtered to `project_ids`; a document type
      is unscoped, because the document source's `resolve` is its gate.

    A candidate is never a permission answer: the consumer materializes every
    id through the owner's read gate before a person sees it. `search` fuses
    each provider's ranking with its full-text one by RRF, time-budgets the
    hybrid call, and reads any exception as "no candidates" — full-text only
    is the floor, and switching the provider off lands exactly there.
    """

    async def enabled(self, session: Any) -> bool: ...
    async def candidates(
        self,
        session: Any,
        entity_type: str,
        q: str,
        *,
        limit: int,
        project_ids: Sequence[Any] | None = None,
    ) -> list[tuple[Any, float]]: ...


@runtime_checkable
class NotificationSubjectProvider(Protocol):
    """Something other than an issue that notifications can be ABOUT (RADD-1385).

    Mechanism only: `notify` owns the kinds × scopes matrix, the planner, the
    channel verdict, the inbox and the mail; an issue is its built-in subject.
    Anything else — a wiki page — registers here under its ENTITY TYPE (the
    IntegrationSpec's name, which is also the comment parent type), and notify
    asks it only what it cannot know itself:

    * `entity_type` — the key above;
    * `scope` — the SUBSCRIPTION scope the subject's container answers to
      (`space` for a page): the prefs picker and a subscription's label ask the
      provider of that scope;
    * `events` — event type → the notification kind it fans out as;
    * `locate(session, event)` — the subject an event is about (one of `events`,
      or a comment whose parent is this entity type), as notify's `SubjectRef`
      (id, container id, the display payload the row is written with), or None;
    * `watcher_ids(session, subject_id)` — who follows it (`participating`);
    * `reader_ids(session, subject_id, user_ids)` — of these people, the ACTIVE
      ones who may read it now. The one read gate: fan-out and the mail loops'
      re-check both ask it;
    * `scope_options(session, actor, *, q, limit, offset, exclude)` — the
      containers the actor may subscribe to, paged `(choices, total)`;
    * `scope_names(session, actor, scope_ids)` — of these containers, the ones
      the actor may NAME, by name. It narrows and labels at once, because the
      label is the whole of what an unchecked subscription id would leak.

    A subject whose provider is gone — the plugin disabled — notifies nobody,
    and its queued rows stop being mailed: nothing is left to vouch for them.
    """

    entity_type: str
    scope: str
    events: Mapping[str, str]

    async def locate(self, session: Any, event: Any) -> Any: ...
    async def watcher_ids(self, session: Any, subject_id: Any) -> set[Any]: ...
    async def reader_ids(self, session: Any, subject_id: Any, user_ids: Any) -> set[Any]: ...
    async def scope_options(
        self, session: Any, actor: Any, *, q: str, limit: int, offset: int, exclude: list[str]
    ) -> tuple[list[Any], int]: ...
    async def scope_names(self, session: Any, actor: Any, scope_ids: Any) -> dict[Any, str]: ...


@runtime_checkable
class NotificationAudienceSource(Protocol):
    """More people PARTICIPATING in an issue than its watchers (RADD-1385).

    `participants` answers with the CURRENT members of the item's participant
    teams — resolved at fan-out time, so joining a team joins its shared
    tickets. Every provider is asked and the answers UNION; each recipient
    still passes notify's per-row read check, so a source can widen who is
    ASKED, never what anyone may see.
    """

    async def participant_ids(self, session: Any, item_id: Any) -> set[Any]: ...


@runtime_checkable
class MailTransport(Protocol):
    """Carries one notification email (RADD-1385).

    `notify` decides who is mailed what; the transport owns sender resolution,
    threading and the `mail.sent`/`mail.failed` record. `mailintake` provides it.
    With none registered email is UNAVAILABLE: notify records the rows as
    undeliverable instead of dialling a relay of its own, and the inbox is
    untouched.

    * `configured(session)` — is there anywhere to send FROM? Asked once per
      loop tick, never per recipient;
    * `send(session, mail)` — deliver notify's `NotificationMail` (its `kind`
      and `failure` are notify's vocabulary). True when it went out; never raises.
    """

    async def configured(self, session: Any) -> bool: ...
    async def send(self, session: Any, mail: Any) -> bool: ...


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


