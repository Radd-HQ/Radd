"""Integration sockets — named interfaces one plugin PROVIDES and others consume.

A provider registers `IntegrationSpec(Socket.X, name, impl=...)`; a consumer reads
`providers(Socket.X)` / `provider(Socket.X, name)` / `single_provider(Socket.X)`, which
answer only for plugins loaded NOW, so disabling a provider withdraws it. Every socket
declares in `SOCKET_POLICIES` what its consumer does with NO provider (RADD-1456)."""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from .registry import registries


class Socket(StrEnum):
    STORAGE_BACKEND = "storage_backend"  # filesystem | s3 (attachments)
    # user_choice | cidr (attachments), llm (ai) — spec 102, RADD-1387
    STORAGE_ROUTING_RULE = "storage_routing_rule"
    TASK_BACKEND = "task_backend"  # localloop (default) | celery
    NON_WORKING_DAYS = "non_working_days"  # calendar dates nobody works (RADD-1031)
    PERSON_AVAILABILITY = "person_availability"  # who is away on a date (RADD-1387)
    TRANSITION_CHECK = "transition_check"  # a workflow transition-rule check (RADD-1383)
    SEARCH_DOCUMENTS = "search_documents"  # non-item hits search shows (RADD-1384)
    SEMANTIC_CANDIDATES = "semantic_candidates"  # meaning-ranked ids for a query (RADD-1384)
    # RADD-1385: what notify learns from optional plugins instead of importing them.
    NOTIFICATION_SUBJECT = "notification_subject"  # a non-item thing notifications are about (pages)
    NOTIFICATION_AUDIENCE = "notification_audience"  # more people following an item (participants)
    MAIL_TRANSPORT = "mail_transport"  # carries a notification email (mailintake)


@dataclass(frozen=True)
class SocketPolicy:
    """What a socket's consumer does when NO provider is live, and how many may be.

    `fails_closed`: the consumer REFUSES what it holds for the socket — a stored
    rule blocks the move, a stored host cannot be opened, a queued row is not
    mailed, no tick runs. Fails open: the consumer proceeds with the empty answer —
    no date is non-working, nobody is away, a stored routing rule of that type falls
    through, search shows issues alone, an item's audience is its watchers.
    `single`: at most one plugin may provide the socket; the registry refuses a
    second (`ContributionConflict`) and `single_provider` refuses to pick between two.
    """

    fails_closed: bool
    single: bool = False


#: Every `Socket` member has a row here (`tests/test_sockets.py` holds it to that);
#: the module map prints it beside the providers and readers.
SOCKET_POLICIES: Mapping[Socket, SocketPolicy] = {
    # `attachments.clients.client_for` raises for a host whose type has no provider.
    Socket.STORAGE_BACKEND: SocketPolicy(fails_closed=True),
    # `attachments.routing.engine.decide` skips a stored rule with no provider.
    Socket.STORAGE_ROUTING_RULE: SocketPolicy(fails_closed=False),
    # `kernel.runtime.schedule_tasks` raises: no loop runs without a backend.
    Socket.TASK_BACKEND: SocketPolicy(fails_closed=True),
    # `slas.calendar`: no provider, no non-working date; the clock runs every day.
    Socket.NON_WORKING_DAYS: SocketPolicy(fails_closed=False),
    # `automations.round_robin`: nobody is away.
    Socket.PERSON_AVAILABILITY: SocketPolicy(fails_closed=False),
    # `workflow.guards.unprovided_failure`: a stored rule with no provider blocks the move.
    Socket.TRANSITION_CHECK: SocketPolicy(fails_closed=True),
    # `search.sources`: issues alone; full text alone.
    Socket.SEARCH_DOCUMENTS: SocketPolicy(fails_closed=False),
    Socket.SEMANTIC_CANDIDATES: SocketPolicy(fails_closed=False),
    # `notify.subjects`: a subject nobody vouches for notifies nobody and its queued rows stop mailing.
    Socket.NOTIFICATION_SUBJECT: SocketPolicy(fails_closed=True),
    # `notify.audience`: the audience is the watchers.
    Socket.NOTIFICATION_AUDIENCE: SocketPolicy(fails_closed=False),
    # `notify.mailer`/`emailer`: queued email rows are recorded undeliverable, not sent.
    Socket.MAIL_TRANSPORT: SocketPolicy(fails_closed=True, single=True),
}

#: A socket a PLUGIN defines (outside `Socket`, like vcs's connector tabs) declares no
#: policy here; it reads as fail-open and multi-provider, which is what a list of tabs is.
PLUGIN_SOCKET_POLICY = SocketPolicy(fails_closed=False)


def socket_policy(socket: Socket | str) -> SocketPolicy:
    try:
        return SOCKET_POLICIES[Socket(str(socket))]
    except ValueError:
        return PLUGIN_SOCKET_POLICY


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


@runtime_checkable
class RoutingRule(Protocol):
    """One storage routing-rule TYPE (spec 102): `evaluate` answers a host id, or None to
    fall through; `config_model` validates its stored config. Optional
    `captured_types(session, config, *, source_ip, content_types)` — the types it decides
    without reaching an "ask the uploader" rule (absent = captures nothing: over-asking beats
    discarding an answer). A stored rule whose provider is gone is skipped."""

    config_model: Any

    async def evaluate(self, session: Any, ctx: Any, config: Any) -> Any: ...


@runtime_checkable
class NonWorkingDaysProvider(Protocol):
    """Calendar dates on which NOBODY works (RADD-1031) — never one person's leave: an SLA
    clock belongs to an item. Every provider is asked and answers UNION, bounded to the
    [start, end] window asked for."""

    async def non_working_dates(self, session: Any, start: date, end: date) -> set[date]: ...


@runtime_checkable
class PersonAvailabilityProvider(Protocol):
    """Which PEOPLE are away on a date (RADD-1387): `away_user_ids(session, day, user_ids)`,
    batched. Per person, unlike NON_WORKING_DAYS — never read it as instance-wide. Answers
    UNION; no provider means nobody is away."""

    async def away_user_ids(self, session: Any, day: date, user_ids: Collection[Any]) -> set[Any]: ...


@runtime_checkable
class TransitionCheckProvider(Protocol):
    """One CHECK a workflow transition rule may name (RADD-1383); workflow evaluates its
    own checks and asks this socket for the rest (`approvals` → `require_approval`).

    * `check` — the rule's key, unique across providers (= the IntegrationSpec name);
    * `sort_last` — its failure reads after workflow's own;
    * `validate(session, params)` — write path: normalized params, or ConflictError;
    * `prepare(session, item)` — per-item data `failure` needs, fetched once;
    * `failure(params, prepared, to_state_id)` — pure: None, or the mover's sentence;
    * `moved(session, item_id, to_state_id)` — told after every state change (an
      approval is spent by the move it unlocked).

    A stored rule whose provider is gone FAILS CLOSED in workflow."""

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
    """A corpus of DOCUMENTS search shows beside issues (RADD-1384); the provider owns its
    ACL end to end.

    * `entity_type` — its id space (also what SEMANTIC_CANDIDATES is asked for);
    * `search(session, actor, q, limit=)` — full-text, best first, readable only, scoped
      BEFORE the limit;
    * `resolve(session, actor, ids)` — the readable subset of `ids`, any order.

    Both return `search.sources.DocumentHit`. No provider = issues alone."""

    entity_type: str

    async def search(self, session: Any, actor: Any, q: str, *, limit: int) -> list[Any]: ...
    async def resolve(self, session: Any, actor: Any, ids: Sequence[Any]) -> list[Any]: ...


@runtime_checkable
class SemanticCandidateSource(Protocol):
    """Meaning-ranked candidates for a query (RADD-1384); `ai` answers from embeddings.

    * `enabled(session)` — can it answer NOW (asked on every hybrid search; keep it cheap);
    * `candidates(session, entity_type, q, limit=, project_ids=)` — `(id, cosine distance)`
      nearest first, `[]` for a type it does not embed; items pre-filtered to `project_ids`.

    A candidate is never a permission answer (every id passes the owner's read gate); any
    exception reads as "no candidates" — full-text only is the floor."""

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
    """Something other than an issue that notifications can be ABOUT (RADD-1385), registered
    under its `entity_type` (the IntegrationSpec name, = the comment parent type); notify asks
    it only what it cannot know.

    * `scope` — the subscription scope its container answers to (`space` for a page);
    * `events` — event type → notification kind;
    * `locate(session, event)` — the notify `SubjectRef` an event is about, or None;
    * `watcher_ids(session, subject_id)` — who follows it;
    * `reader_ids(session, subject_id, user_ids)` — the ACTIVE ones who may read it now
      (the one read gate for fan-out and mail re-checks);
    * `scope_options(session, actor, *, q, limit, offset, exclude)` — subscribable
      containers, paged `(choices, total)`;
    * `scope_names(session, actor, scope_ids)` — the ones the actor may NAME (narrows and
      labels at once: the label is all an unchecked subscription id would leak).

    With its provider gone a subject notifies nobody and its queued rows stop mailing."""

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
    """More people following an issue than its watchers (RADD-1385): `participants`
    answers with its teams' CURRENT members. Answers UNION; recipients still pass notify's
    per-row read check."""

    async def participant_ids(self, session: Any, item_id: Any) -> set[Any]: ...


@runtime_checkable
class MailTransport(Protocol):
    """Carries one notification email (RADD-1385); `mailintake` provides it and owns sender
    resolution, threading and the mail.sent/mail.failed record. With none, notify records
    rows as undeliverable.

    * `configured(session)` — anywhere to send FROM? (once per tick);
    * `send(session, mail)` — deliver a `NotificationMail`; True when sent, never raises."""

    async def configured(self, session: Any) -> bool: ...
    async def send(self, session: Any, mail: Any) -> bool: ...


# --- resolution helpers (over the kernel integrations registry) ---


def providers(socket: Socket | str) -> dict[str, Any]:
    """All registered providers of a socket → {name: impl}, in registration order."""
    return {n: ig.impl for n, ig in registries.providers(str(socket)).items()}


def provider(socket: Socket | str, name: str) -> Any:
    ig = registries.integration(str(socket), name)
    return ig.impl if ig else None


class AmbiguousProvider(LookupError):
    """More than one provider answers where the consumer needs exactly one."""


def single_provider(
    socket: Socket | str,
    where: Callable[[Any], bool] | None = None,
    *,
    what: str = "",
) -> Any:
    """The ONE provider of a socket, or None — for a single-provider socket, or with
    `where`, the one provider of a multi-provider socket that a condition picks out
    (the subject provider claiming an event type). Two is a configuration error the
    consumer must not paper over by taking the first: it raises, naming them. Read on
    every call, never cached, so a disable applies at once."""
    live = registries.providers(str(socket))
    matches = {n: ig.impl for n, ig in live.items() if where is None or where(ig.impl)}
    if len(matches) > 1:
        raise AmbiguousProvider(
            f"{len(matches)} providers of {socket}{' for ' + what if what else ''}: "
            + ", ".join(sorted(matches))
        )
    return next(iter(matches.values()), None)


