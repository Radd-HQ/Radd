"""Trigger classification + condition matching + the read-only action planner,
split out of `engine.py` (RADD-902) along its own "loop guard + trigger
classification" / "condition matching" / "action planning" markers (formerly
lines 72-425) — the planning-vs-applying seam the audit called out as the
file's cleanest cut.

Nothing here writes to the database or calls another module's service to
MUTATE anything; `_plan` resolves one stored action into a `_Plan` the caller
(`engine._apply_plan`) then executes. `engine.py` imports this module (never
the other way — nothing here needs anything `engine.py` defines) and
re-exports the public/test-visible names under its own name, so
`from radd.modules.automations.engine import _plan, condition_matches, ...`
is unaffected.

`_signed_headers` did NOT move here even though it sits physically inside the
original "action planning" section, right after `_plan` — its only consumer
is `_apply_plan`, which is application code that stays in `engine.py`. Private
helpers move with their consumer, not with the section they happened to be
typed under.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentVisibility
from radd.modules.cycles import service as cycles_service
from radd.modules.events.service import Event
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.items import service as items, slq
from radd.modules.items.enums import ItemEntity, ItemKind, ItemVisibility, Priority
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
from datetime import date

from radd.modules.items.slq.helpers import relative_date
from radd.modules.items.slq.parser import Value
from radd.modules.itemtypes import service as itemtypes_service
from radd.modules.items.service import queries as items_queries
from radd.modules.releases import service as releases_service
from radd.modules.teams import service as teams_service
from radd.modules.workflow import service as workflow

from . import catalog, conditions, round_robin
from .email_action import is_role, outbound_available, resolve_recipient, resolve_user
from .templating import Renderer
from .types import (
    CLEAR_VALUE,
    SYSTEM_ACTOR_ID,
    ActionType,
    AutomationEvent,
    PlanKind,
)

# --- loop guard + trigger classification ---


def is_automation_caused(event: Event) -> bool:
    """True if this event was emitted by an engine-applied mutation (the loop guard).

    Reads the event's own `automated` marker, not its actor. Since spec 116 an
    action may run AS a real person, so "the actor is the system user" no longer
    answers "did an automation cause this" — and inferring it from identity would
    let any act-as automation re-trigger itself forever.

    The actor check stays as a second arm: the scheduler and older rows predate
    the marker, and an event with the system actor is automation-caused either
    way."""
    return bool(getattr(event, "automated", False)) or event.actor_id == SYSTEM_ACTOR_ID


def should_process(event: Event) -> bool:
    """A human/API event on a subscribable type — never an automation-caused one.
    EXCEPTION (spec 69): the scheduler's synthetic `automation.scheduled` event is
    system-emitted by design, so it bypasses the loop-guard skip — loop safety
    holds because the item events a scheduled run emits carry the system actor,
    which this predicate still rejects on the EVENT-rule path.

    `silent` events (a bulk import, `events.quiet()`) never match: a rule that
    assigns on create or transitions on a field change would otherwise fire once
    per imported issue and rewrite the history being imported. Checked ahead of
    the scheduled-event exception — an import is silent whatever it emits."""
    if event.silent:
        return False
    if event.event_type == AutomationEvent.SCHEDULED.value:
        return True
    return event.event_type in catalog.TRIGGERS and not is_automation_caused(event)


async def _resolve_target_item(session: AsyncSession, event: Event) -> WorkItem | None:
    """The item a rule's actions apply to.

    ONE rule since RADD-922: `payload.item.id`, which every item-scoped event
    carries. It used to be two — the entity id when the entity was an item, the
    payload's `item_id` otherwise — because the item events were the only ones
    that did not name the item in their payload. The entity fallback stays for
    the item events' own `entity_id`, which is the same value and free.
    """
    raw = ((event.payload or {}).get("item") or {}).get("id")
    if not raw and event.entity_type == ItemEntity.ITEM.value:
        raw = event.entity_id
    if not raw:
        return None
    try:
        item_id = uuid.UUID(str(raw))
    except ValueError:
        return None
    return await session.get(WorkItem, item_id)


async def _event_facts(session: AsyncSession, event: Event) -> conditions.EventFacts:
    actor = (
        await session.get(User, event.actor_id) if event.actor_id is not None else None
    )
    return conditions.EventFacts(
        event_type=event.event_type,
        actor_id=str(event.actor_id) if event.actor_id else None,
        actor_email=actor.email if actor else None,
        actor_name=actor.name if actor else None,
        payload=event.payload or {},
    )


# --- condition matching (reuses the SLQ compiler, filtered to the one item) ---


async def _project_definitions(
    session: AsyncSession, project: Project
) -> dict[str, FieldDefinition]:
    by_key: dict[str, FieldDefinition] = {}
    for definition in await fields.definitions_for_project(session, project):
        by_key.setdefault(definition.key, definition)
    return by_key


async def condition_matches(
    session: AsyncSession, condition_slq: str, item: WorkItem, project: Project
) -> bool:
    """Does the item satisfy the rule's condition? Empty condition = always. Reuses the
    SLQ compiler and runs the compiled WHERE guarded to this single item id."""
    text = (condition_slq or "").strip()
    if not text:
        return True
    compiled = await slq.compile_query(
        session,
        slq.parse(text),
        definitions_by_key=await _project_definitions(session, project),
        current_user_id=SYSTEM_ACTOR_ID,
        project_id=project.id,
    )
    stmt = select(WorkItem.id).where(WorkItem.id == item.id)
    if compiled.where is not None:
        stmt = stmt.where(compiled.where)
    return await session.scalar(stmt) is not None


# --- action planning (shared by apply + dry-run preview; resolution does no writes) ---


@dataclass
class _Plan:
    kind: PlanKind
    detail: str
    item_update: ItemUpdate | None = None
    comment: CommentCreate | None = None
    item_create: ItemCreate | None = None
    # (url, json_body, signing_secret) for send_webhook / post_chat.
    http: tuple[str, dict[str, Any], dict[str, str]] | None = None
    # (user_id, message) for notify_user.
    notify: tuple[uuid.UUID, str] | None = None
    # (to_address, to_name, subject, body) for send_email (spec 66).
    email: tuple[str, str, str, str] | None = None
    # (team_id, assigned_user_id) for assign_round_robin (RADD-1044): applied
    # ALONGSIDE the item_update, so the rotation advances in the same SAVEPOINT as
    # the assignment it describes. Read-only here — the write is `_apply_plan`'s.
    cursor_advance: tuple[uuid.UUID, uuid.UUID] | None = None
    # RADD-1267 — the verbs that are not field writes, each applied through the
    # owning module's service by `_apply_plan`:
    # (target item id, link type key) for link_item.
    link: tuple[uuid.UUID, str] | None = None
    # True/False for archive_item.
    archive: bool | None = None
    # user id for add_watcher / add_participant.
    person: uuid.UUID | None = None
    # target project id for move_to_project.
    move_to: uuid.UUID | None = None
    #: `{{token}}` -> what it rendered to on this invocation (spec 120). LAST in
    #: the field order because every other field is passed positionally by some
    #: branch below, and stamped by `_plan` after the planner returns — twenty
    #: return sites each remembering to carry it is exactly how one of them
    #: would not.
    resolved: dict[str, str] = field(default_factory=dict)


def _manual_facts() -> conditions.EventFacts:
    """Stand-in facts for manual runs / previews — templates degrade verbatim."""
    return conditions.EventFacts(
        event_type="manual", actor_id=None, actor_email=None, actor_name=None, payload={}
    )


async def _plan_create_item(
    session: AsyncSession,
    params: dict,
    target: Project,
    system_user: User,
    text: Renderer,
) -> "_Plan":
    """Resolve every named target into the ItemCreate the items service wants.

    Names, not ids, all the way through — an automation is written against a
    project's vocabulary ("In Review", "Bug", "alice@…") and must keep working
    when the underlying rows are recreated. Anything that will not resolve
    SKIPS with the name in the message, because a create that silently drops the
    assignee is worse than one that does not happen.
    """
    priority = Priority.NORMAL
    if params.get("priority"):
        priority = _priority_or_none(text.line(params["priority"]))
        if priority is None:
            return _Plan(
                PlanKind.SKIP,
                f"create_item: {text.line(params['priority'])!r} is not a priority "
                f"({_vocabulary(p.value for p in Priority)})",
            )
    create_kwargs: dict[str, Any] = {
        "project_id": target.id,
        "title": text.line(params["title"]),
        "description": text(params.get("description", "")),
        "priority": priority,
        "flagged": bool(params.get("flagged")),
    }
    if params.get("kind"):
        create_kwargs["kind"] = ItemKind(params["kind"])
    if params.get("estimate_points") is not None:
        create_kwargs["estimate_points"] = params["estimate_points"]

    if name := params.get("type"):
        found = next(
            (t for t in await itemtypes_service.list_types(session, target.id)
             if t.name == text.line(name)),
            None,
        )
        if found is None:
            return _Plan(PlanKind.SKIP, f"create_item: no issue type {name!r} in {target.key}")
        create_kwargs["type_id"] = found.id
    if name := params.get("state"):
        found = await _state_by_name(session, target.id, text.line(name))
        if found is None:
            return _Plan(PlanKind.SKIP, f"create_item: no state {name!r} in {target.key}")
        create_kwargs["state_id"] = found.id
    for key in ("assignee", "reporter"):
        if value := params.get(key):
            if _is_clear(str(value)):
                continue
            found = await auth.get_user_by_email(session, text.line(value))
            if found is None:
                return _Plan(PlanKind.SKIP, f"create_item: no user {value!r} for {key}")
            create_kwargs[f"{key}_id"] = found.id
    if name := params.get("team"):
        found = await _team_by_name(session, text.line(name))
        if found is None:
            return _Plan(PlanKind.SKIP, f"create_item: no team {name!r}")
        create_kwargs["team_id"] = found.id
    if name := params.get("cycle"):
        found = await _cycle_by_name(session, text.line(name))
        if found is None:
            return _Plan(PlanKind.SKIP, f"create_item: no cycle {name!r}")
        create_kwargs["cycle_id"] = found.id
    if version := params.get("release"):
        found = await releases_service.resolve_release(session, target.id, text.line(version))
        if found is None:
            return _Plan(PlanKind.SKIP, f"create_item: no release {version!r} in {target.key}")
        create_kwargs["release_id"] = found.id
    if key := params.get("parent"):
        found = await items_queries.find_item_by_key(session, text.line(key))
        if found is None:
            return _Plan(PlanKind.SKIP, f"create_item: no item {key!r} to parent under")
        create_kwargs["parent_id"] = found.id
    for date_field in ("start_date", "target_date"):
        if value := params.get(date_field):
            resolved = _resolve_date(text.line(value))
            if resolved is None:
                return _Plan(PlanKind.SKIP, f"create_item: {date_field} {value!r} is not a date")
            create_kwargs[date_field] = resolved

    labels = [text.line(label) for label in (params.get("labels") or []) if str(label).strip()]
    custom = {
        key: text(value) if isinstance(value, str) else value
        for key, value in (params.get("custom_fields") or {}).items()
    }
    if labels:
        create_kwargs["labels"] = labels
    if custom:
        # Validated by the items service against the target project's field
        # definitions — the same path a human create takes, rather than a second
        # validator here that could disagree with it.
        create_kwargs["custom_fields"] = custom

    try:
        create = ItemCreate(**create_kwargs)
    except ValidationError as invalid:
        # A RENDERED value the item schema will not take — a title past 500
        # characters is the one a model produces without trying. Skipped with
        # the validator's own words, because the alternative is this raising
        # through `_one`'s generic handler: a dry run that says "Would apply"
        # and a live run that logs a crash and records nothing.
        return _Plan(PlanKind.SKIP, f"create_item: {_validation_reason(invalid)}")
    return _Plan(
        PlanKind.CREATE_ITEM,
        f"create_item in {target.key}: {create.title!r}",
        item_create=create,
    )


#: How many names a "did you mean" hint lists before it becomes a wall.
_VOCABULARY_LIMIT = 12


def _vocabulary(names, limit: int = _VOCABULARY_LIMIT) -> str:
    """A hint naming what WOULD have resolved (spec 120).

    Only ever built from a collection the planner ALREADY HAS — the states it
    just listed, the enum it just failed to coerce. Never a second query for the
    sake of a message: a skip is already the unhappy path, and paying a round
    trip to phrase it better is how a nightly run over 200 items gets slower
    every time something is misconfigured. Capped, because forty team names in
    an error is not a hint.
    """
    seen = [str(name) for name in names]
    shown = ", ".join(seen[:limit])
    return f"{shown}, …" if len(seen) > limit else shown


def _validation_reason(invalid: ValidationError) -> str:
    """A pydantic failure in the words of the field that failed."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'value'}: {error['msg']}"
        for error in invalid.errors()
    )


def _priority_or_none(value: str) -> Priority | None:
    try:
        return Priority(value)
    except ValueError:
        return None


def _resolve_date(value: str) -> date | None:
    """An ISO date, or a relative literal the SLQ vocabulary already knows."""
    relative = relative_date(Value(value), date.today())
    if relative is not None:
        return relative
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


#: What `{{item.*}}` can say beyond the row itself (RADD-1265), per item id.
#: Loaded ONCE per action node by `load_item_facts` — names, not ids, because a
#: token exists to be read by a person and `{{item.assignee}}` rendering a uuid
#: is the notification-shaped mistake RADD-922 removed from the payloads.
ItemFacts = dict[str, Any]


async def load_item_facts(
    session: AsyncSession, rows: list[tuple[WorkItem, Project | None]]
) -> dict[uuid.UUID, ItemFacts]:
    """State, people, type and labels for every item in `rows`, in four batched
    queries. Empty rows cost nothing."""
    # Spine models may be READ directly (RADD-885); labels and issue types are
    # not spine, so they answer through their services.
    from radd.modules.items.models import ItemLabel
    from radd.modules.labels import service as labels_service
    from radd.modules.workflow.models import State

    if not rows:
        return {}
    items_by_id = {item.id: item for item, _ in rows}
    state_ids = {item.state_id for item in items_by_id.values() if item.state_id}
    user_ids = {
        uid
        for item in items_by_id.values()
        for uid in (item.assignee_id, item.reporter_id)
        if uid is not None
    }
    type_ids = {item.type_id for item in items_by_id.values() if item.type_id}
    states = {
        row.id: row
        for row in (await session.execute(select(State).where(State.id.in_(state_ids)))).scalars()
    } if state_ids else {}
    users = {
        row.id: row
        for row in (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars()
    } if user_ids else {}
    types = await itemtypes_service.types_by_ids(session, type_ids)
    attached = (
        await session.execute(
            select(ItemLabel.item_id, ItemLabel.label_id).where(ItemLabel.item_id.in_(items_by_id))
        )
    ).all()
    label_rows = await labels_service.labels_by_ids(session, {label_id for _, label_id in attached}) if attached else {}
    labels: dict[uuid.UUID, list[str]] = {}
    for item_id, label_id in attached:
        label = label_rows.get(label_id)
        if label is not None:
            labels.setdefault(item_id, []).append(label.name)
    for names in labels.values():
        names.sort()

    facts: dict[uuid.UUID, ItemFacts] = {}
    for item in items_by_id.values():
        state = states.get(item.state_id)
        assignee = users.get(item.assignee_id) if item.assignee_id else None
        reporter = users.get(item.reporter_id) if item.reporter_id else None
        issue_type = types.get(item.type_id) if item.type_id else None
        facts[item.id] = {
            "state": state.name if state else "",
            "state_category": state.category if state else "",
            "assignee": assignee.name if assignee else "",
            "reporter": reporter.name if reporter else "",
            "type": issue_type.name if issue_type else "",
            "labels": ", ".join(labels.get(item.id, [])),
        }
    return facts


def _item_ctx(
    item: WorkItem | None, project: Project | None, facts: ItemFacts | None = None
) -> dict[str, Any] | None:
    if item is None or project is None:
        return None
    key = f"{project.key}-{item.number}"
    return {
        "key": key,
        "title": item.title,
        "id": str(item.id),
        "url": f"{settings.app_base_url.rstrip('/')}/issues/{key}",
        "project": project.key,
        "priority": str(item.priority or ""),
        # Blank rather than absent: an unassigned item's `{{item.assignee}}`
        # renders as nothing, not as the literal token.
        **{
            name: ""
            for name in ("state", "state_category", "assignee", "reporter", "type", "labels")
        },
        **(facts or {}),
    }


def items_ctx(
    scope: list[tuple[WorkItem, Project | None]],
    facts: dict[uuid.UUID, ItemFacts] | None = None,
) -> list[dict[str, Any]]:
    """The set an action is speaking for, as template/webhook context.

    One shape for both arities (RADD-918): the whole packet when the action runs
    once, the single item when it runs per item. That is what lets `{{items.keys}}`
    and the webhook's `items[]` read correctly in either mode without the planner
    knowing which one it is in.
    """
    facts = facts or {}
    return [
        ctx
        for item, project in scope
        if (ctx := _item_ctx(item, project, facts.get(item.id))) is not None
    ]


def _is_clear(value: str) -> bool:
    return value.strip().lower() == CLEAR_VALUE


def _named(rows, name: str):
    """The row with this name, or None. Split out so a branch that wants the
    VOCABULARY for its skip message can hold the list it already fetched instead
    of asking again (spec 120)."""
    return next((row for row in rows if row.name == name), None)


async def _state_by_name(session: AsyncSession, project_id: uuid.UUID, name: str):
    return _named(await workflow.list_states(session, project_id), name)


async def _team_by_name(session: AsyncSession, name: str):
    return _named(await teams_service.list_teams(session), name)


async def _cycle_by_name(session: AsyncSession, name: str):
    return _named(await cycles_service.list_cycles(session), name)


async def _current_labels(session: AsyncSession, item: WorkItem, system_user: User) -> list[str]:
    read = await items.get_item(session, item.id, actor=system_user)
    return list(read.labels)


async def _item_by_key(session: AsyncSession, key: str, actor: User) -> WorkItem | None:
    """An item by `TD-42`, or None — the by-key seam raises, and a planner
    answers with a skip rather than an exception."""
    try:
        read = await items.get_item_by_key(session, key.strip().upper(), actor)
    except Exception:  # malformed, unknown or unreadable key: to a planner all three are "no item", a skip naming the key
        return None
    return await session.get(WorkItem, read.id)


async def _project_by_key(session: AsyncSession, key: str) -> Project | None:
    for project in await projects_service.list_projects(session):
        if project.key.casefold() == key.strip().casefold():
            return project
    return None


async def _plan(
    session: AsyncSession,
    action: dict,
    item: WorkItem | None,
    project: Project | None,
    system_user: User,
    *,
    facts: conditions.EventFacts,
    rule_name: str,
    items: list[dict[str, Any]] | None = None,
    variables: Any = None,
    item_facts: ItemFacts | None = None,
) -> _Plan:
    """Resolve one stored action — read-only. Returns the work to perform, or a
    'skip' plan when a named target no longer resolves (logged, not fatal).

    `item` is the ONE item this invocation targets (per-item arity, or a set of
    exactly one); `items` is everything it speaks for, which is what the
    set-shaped tokens and the webhook body render from. Both are supplied by the
    executor, so the planner never asks which arity it is in.

    `variables` is the packet's bag (spec 120) — what upstream nodes produced,
    readable as `{{<node>.<field>}}` anywhere a token already worked. A THIN
    WRAPPER around `_plan_action` so the renderer is built once and its record of
    what it substituted is stamped onto whatever plan comes back: twenty return
    sites each remembering to carry it is exactly how one of them would not.
    """
    render = Renderer(
        facts=facts,
        item_ctx=_item_ctx(item, project, item_facts),
        items=items,
        variables=variables or {},
    )
    plan = await _plan_action(
        session, action, item, project, system_user,
        facts=facts, rule_name=rule_name, items=items, text=render,
    )
    if render.misses:
        # A VARIABLE token that found nothing OVERRIDES whatever the planner
        # concluded, including a skip of its own. `set_state {{triage.state}}`
        # with no `triage` on this branch would otherwise report "no state
        # '{{triage.state}}' in TD" — technically true, and it sends the reader
        # to the workflow settings for a problem that is in the wiring.
        #
        # It is a SKIP rather than an error because the branch is allowed to be
        # conditional: an `unavailable` port that nobody wired means the model
        # did not answer, and the actions that needed its answer should not
        # happen — quietly is the bug, refusing the whole run is worse.
        return _Plan(
            PlanKind.SKIP,
            f"{action['type']}: {'; '.join(render.misses)}",
            resolved=dict(render.resolved),
        )
    plan.resolved = dict(render.resolved)
    return plan


async def _plan_action(
    session: AsyncSession,
    action: dict,
    item: WorkItem | None,
    project: Project | None,
    system_user: User,
    *,
    facts: conditions.EventFacts,
    rule_name: str,
    items: list[dict[str, Any]] | None,
    text: Renderer,
) -> _Plan:
    """The per-action-type resolution. Split from `_plan` so the renderer can be
    owned by the caller and interrogated after every branch."""
    action_type = ActionType(action["type"])
    params = action["params"]
    ictx = text.item_ctx
    match action_type:
        case ActionType.CREATE_ITEM:
            target = await _project_by_key(session, text.line(params["project"]))
            if target is None:
                return _Plan(PlanKind.SKIP, f"create_item: no project {params['project']!r}")
            return await _plan_create_item(session, params, target, system_user, text)
        case ActionType.SEND_WEBHOOK:
            body = {
                "rule": rule_name,
                "event_type": facts.event_type,
                "actor": {
                    "id": facts.actor_id,
                    "email": facts.actor_email,
                    "name": facts.actor_name,
                },
                "item": ictx,
                # The SET, which the body could not carry before (RADD-918): a
                # scheduled run posted `"item": null` and a count, so a receiver
                # could not tell which issues the automation was about.
                "items": items or [],
                "payload": facts.payload,
            }
            return _Plan(
                PlanKind.HTTP,
                f"send_webhook -> {params['url']}",
                http=(params["url"], body, params.get("secret", "")),
            )
        case ActionType.POST_CHAT:
            return _Plan(
                PlanKind.HTTP,
                f"post_chat -> {params['webhook_url']}",
                http=(params["webhook_url"], {"text": text(params["message"])}, ""),
            )
        case ActionType.NOTIFY_USER:
            target_user = params["user"]
            if is_role(target_user):
                # A role names a property of ONE item — per-item arity supplies
                # it. "Notify the assignee" was previously inexpressible: the
                # param took a literal address only.
                user_id = await resolve_user(session, target_user, item)
                if user_id is None:
                    return _Plan(
                        PlanKind.SKIP, f"notify_user: no {target_user} on the target item"
                    )
                return _Plan(
                    PlanKind.NOTIFY,
                    f"notify_user ({target_user})",
                    notify=(user_id, text(params["message"])),
                )
            user = await auth.get_user_by_email(session, text.line(target_user))
            if user is None:
                return _Plan(PlanKind.SKIP, f"notify_user: no user {target_user!r}")
            return _Plan(
                PlanKind.NOTIFY,
                f"notify_user {target_user}",
                notify=(user.id, text(params["message"])),
            )
        case ActionType.SEND_EMAIL:
            if not await outbound_available(session):
                return _Plan(
                    PlanKind.SKIP,
                    "send_email: no outbound mail sender is configured (Settings → Email)",
                )
            recipient = await resolve_recipient(session, text.line(params["to"]), item)
            if recipient is None:
                return _Plan(PlanKind.SKIP, f"send_email: no recipient resolves for {params['to']!r}")
            address, name = recipient
            return _Plan(
                PlanKind.EMAIL,
                f"send_email -> {address}",
                email=(address, name, text.line(params["subject"]), text(params["body"])),
            )
        case ActionType.SET_STATE:
            # Every named target below renders as a TEMPLATE first (spec 120), so
            # `{{triage.state}}` is a state name the same way a literal is. The
            # rendering is the only change: resolution still goes through the
            # by-NAME seam that was already here, which is what keeps an
            # automation written against a project's vocabulary working when the
            # rows behind it are recreated.
            name = text.line(params["state"])
            states = await workflow.list_states(session, project.id)
            state = _named(states, name)
            if state is None:
                return _Plan(
                    PlanKind.SKIP,
                    f"set_state: no state {name!r} in {project.key} "
                    f"(states: {_vocabulary(s.name for s in states)})",
                )
            return _Plan(PlanKind.ITEM_UPDATE, f"set_state -> {name!r}", ItemUpdate(state_id=state.id))
        case ActionType.SET_PRIORITY:
            rendered = text.line(params["priority"])
            priority = _priority_or_none(rendered)
            if priority is None:
                return _Plan(
                    PlanKind.SKIP,
                    f"set_priority: {rendered!r} is not a priority "
                    f"({_vocabulary(p.value for p in Priority)})",
                )
            return _Plan(
                PlanKind.ITEM_UPDATE, f"set_priority -> {priority.value}", ItemUpdate(priority=priority)
            )
        case ActionType.SET_ASSIGNEE:
            email = text.line(params["assignee"])
            if _is_clear(email):
                return _Plan(PlanKind.ITEM_UPDATE, "set_assignee -> none", ItemUpdate(assignee_id=None))
            user = await auth.get_user_by_email(session, email)
            if user is None:
                # No vocabulary hint: every address on the instance is neither a
                # list this planner has in hand nor something to print.
                return _Plan(PlanKind.SKIP, f"set_assignee: no user {email!r}")
            return _Plan(PlanKind.ITEM_UPDATE, f"set_assignee -> {email}", ItemUpdate(assignee_id=user.id))
        case ActionType.ASSIGN_ROUND_ROBIN:
            name = text.line(params["team"])
            teams = await teams_service.list_teams(session)
            team = _named(teams, name)
            if team is None:
                return _Plan(
                    PlanKind.SKIP,
                    f"assign_round_robin: no team {name!r} "
                    f"(teams: {_vocabulary(t.name for t in teams)})",
                )
            chosen = await round_robin.pick_next(session, team)
            if chosen is None:
                # Every member is inactive or away (or the team is empty): leave the
                # item unassigned rather than clearing whoever it had, and do NOT
                # advance the cursor — nothing was assigned to advance past.
                return _Plan(
                    PlanKind.SKIP,
                    f"assign_round_robin: no eligible member in team {name!r} "
                    "(all inactive or away)",
                )
            return _Plan(
                PlanKind.ITEM_UPDATE,
                f"assign_round_robin -> {name!r}",
                ItemUpdate(assignee_id=chosen),
                cursor_advance=(team.id, chosen),
            )
        case ActionType.SET_TEAM:
            name = text.line(params["team"])
            if _is_clear(name):
                return _Plan(PlanKind.ITEM_UPDATE, "set_team -> none", ItemUpdate(team_id=None))
            teams = await teams_service.list_teams(session)
            team = _named(teams, name)
            if team is None:
                return _Plan(
                    PlanKind.SKIP,
                    f"set_team: no team {name!r} (teams: {_vocabulary(t.name for t in teams)})",
                )
            return _Plan(PlanKind.ITEM_UPDATE, f"set_team -> {name!r}", ItemUpdate(team_id=team.id))
        case ActionType.ADD_LABEL:
            label = text.line(params["label"])
            current = await _current_labels(session, item, system_user)
            new = current if label in current else [*current, label]
            note = " (already present)" if label in current else ""
            return _Plan(PlanKind.ITEM_UPDATE, f"add_label {label!r}{note}", ItemUpdate(labels=new))
        case ActionType.REMOVE_LABEL:
            label = text.line(params["label"])
            current = await _current_labels(session, item, system_user)
            if label not in current:
                return _Plan(
                    PlanKind.SKIP,
                    f"remove_label: {label!r} not on item (it has: {_vocabulary(current) or 'no labels'})",
                )
            new = [name for name in current if name != label]
            return _Plan(PlanKind.ITEM_UPDATE, f"remove_label {label!r}", ItemUpdate(labels=new))
        case ActionType.SET_CYCLE:
            name = text.line(params["cycle"])
            if _is_clear(name):
                return _Plan(PlanKind.ITEM_UPDATE, "set_cycle -> none", ItemUpdate(cycle_id=None))
            cycles = await cycles_service.list_cycles(session)
            cycle = _named(cycles, name)
            if cycle is None:
                return _Plan(
                    PlanKind.SKIP,
                    f"set_cycle: no cycle {name!r} (cycles: {_vocabulary(c.name for c in cycles)})",
                )
            return _Plan(PlanKind.ITEM_UPDATE, f"set_cycle -> {name!r}", ItemUpdate(cycle_id=cycle.id))
        case ActionType.SET_RELEASE:
            version = text.line(params["release"])
            if _is_clear(version):
                return _Plan(PlanKind.ITEM_UPDATE, "set_release -> none", ItemUpdate(release_id=None))
            release = await releases_service.resolve_release(session, project.id, version)
            if release is None:
                # `resolve_release` answers about ONE version; listing every
                # release of the project would be the second query this
                # deliberately does not make.
                return _Plan(PlanKind.SKIP, f"set_release: no release {version!r} in {project.key}")
            return _Plan(
                PlanKind.ITEM_UPDATE, f"set_release -> {version!r}", ItemUpdate(release_id=release.id)
            )
        case ActionType.SET_CUSTOM_FIELD:
            key, value = params["key"], params["value"]
            # Strings only: a select's option and a text field's content are
            # exactly where a token belongs, and rendering a number or a boolean
            # would turn it into one.
            resolved_value = text(value) if isinstance(value, str) else value
            return _Plan(
                PlanKind.ITEM_UPDATE,
                f"set_custom_field {key!r}",
                ItemUpdate(custom_fields={key: resolved_value}),
            )
        case ActionType.SET_PARENT:
            key = text.line(params["parent"])
            if _is_clear(key):
                return _Plan(PlanKind.ITEM_UPDATE, "set_parent -> none", ItemUpdate(parent_id=None))
            parent = await _item_by_key(session, key, system_user)
            if parent is None:
                return _Plan(PlanKind.SKIP, f"set_parent: no item {key!r}")
            if parent.id == item.id:
                return _Plan(PlanKind.SKIP, f"set_parent: {key} cannot be its own parent")
            return _Plan(PlanKind.ITEM_UPDATE, f"set_parent -> {key}", ItemUpdate(parent_id=parent.id))
        case ActionType.SET_TYPE:
            name = text.line(params["type"])
            types = await itemtypes_service.list_types(session, project.id)
            issue_type = _named(types, name)
            if issue_type is None:
                return _Plan(
                    PlanKind.SKIP,
                    f"set_type: no issue type {name!r} in {project.key} "
                    f"(types: {_vocabulary(t.name for t in types)})",
                )
            return _Plan(PlanKind.ITEM_UPDATE, f"set_type -> {name!r}", ItemUpdate(type_id=issue_type.id))
        case ActionType.SET_REPORTER:
            email = text.line(params["reporter"])
            user = await auth.get_user_by_email(session, email)
            if user is None:
                return _Plan(PlanKind.SKIP, f"set_reporter: no user {email!r}")
            return _Plan(PlanKind.ITEM_UPDATE, f"set_reporter -> {email}", ItemUpdate(reporter_id=user.id))
        case ActionType.SET_DATES:
            fields_: dict[str, Any] = {}
            described: list[str] = []
            for param, column in (("start", "start_date"), ("target", "target_date")):
                raw = text.line(str(params.get(param) or ""))
                if not raw:
                    continue
                if _is_clear(raw):
                    fields_[column] = None
                    described.append(f"{param} cleared")
                    continue
                resolved = _resolve_date(raw)
                if resolved is None:
                    return _Plan(PlanKind.SKIP, f"set_dates: {raw!r} is not a date (ISO, or today+3d)")
                fields_[column] = resolved
                described.append(f"{param} -> {resolved.isoformat()}")
            if not fields_:
                return _Plan(PlanKind.SKIP, "set_dates: nothing to set")
            return _Plan(PlanKind.ITEM_UPDATE, f"set_dates {', '.join(described)}", ItemUpdate(**fields_))
        case ActionType.SET_ESTIMATE:
            raw = text.line(params["points"])
            if _is_clear(raw):
                return _Plan(PlanKind.ITEM_UPDATE, "set_estimate -> none", ItemUpdate(estimate_points=None))
            try:
                points = float(raw)
            except ValueError:
                return _Plan(PlanKind.SKIP, f"set_estimate: {raw!r} is not a number")
            if not 0 <= points <= 999:
                return _Plan(PlanKind.SKIP, f"set_estimate: {points} is outside 0–999")
            return _Plan(PlanKind.ITEM_UPDATE, f"set_estimate -> {points:g}", ItemUpdate(estimate_points=points))
        case ActionType.SET_FLAG:
            flagged = bool(params.get("flagged", True))
            return _Plan(PlanKind.ITEM_UPDATE, f"set_flag -> {'flagged' if flagged else 'unflagged'}", ItemUpdate(flagged=flagged))
        case ActionType.SET_VISIBILITY:
            visibility_ = ItemVisibility(str(params["visibility"]))
            return _Plan(
                PlanKind.ITEM_UPDATE, f"set_visibility -> {visibility_.value}", ItemUpdate(visibility=visibility_)
            )
        case ActionType.LINK_ITEM:
            key = text.line(params["target"])
            target_item = await _item_by_key(session, key, system_user)
            if target_item is None:
                return _Plan(PlanKind.SKIP, f"link_item: no item {key!r}")
            if target_item.id == item.id:
                return _Plan(PlanKind.SKIP, f"link_item: {key} cannot link to itself")
            link_type = str(params["link_type"]).strip()
            return _Plan(PlanKind.LINK, f"link_item {link_type} -> {key}", link=(target_item.id, link_type))
        case ActionType.ARCHIVE_ITEM:
            archived = bool(params.get("archived", True))
            if bool(item.archived_at) == archived:
                return _Plan(PlanKind.SKIP, f"archive_item: already {'archived' if archived else 'live'}")
            return _Plan(PlanKind.ARCHIVE, "archive_item" if archived else "archive_item -> restore", archive=archived)
        case ActionType.ADD_WATCHER | ActionType.ADD_PARTICIPANT:
            verb = action_type.value
            target_user = params["user"]
            if is_role(target_user):
                user_id = await resolve_user(session, target_user, item)
                if user_id is None:
                    return _Plan(PlanKind.SKIP, f"{verb}: no {target_user} on the target item")
                who = target_user
            else:
                email = text.line(target_user)
                user = await auth.get_user_by_email(session, email)
                if user is None:
                    return _Plan(PlanKind.SKIP, f"{verb}: no user {email!r}")
                user_id, who = user.id, email
            kind = PlanKind.WATCH if action_type is ActionType.ADD_WATCHER else PlanKind.PARTICIPANT
            return _Plan(kind, f"{verb} {who}", person=user_id)
        case ActionType.MOVE_TO_PROJECT:
            key = text.line(params["project"])
            target = await _project_by_key(session, key)
            if target is None:
                return _Plan(PlanKind.SKIP, f"move_to_project: no project {key!r}")
            if target.id == project.id:
                return _Plan(PlanKind.SKIP, f"move_to_project: already in {key}")
            return _Plan(PlanKind.MOVE, f"move_to_project -> {key}", move_to=target.id)
        case ActionType.ADD_COMMENT:
            visibility = CommentVisibility(params.get("visibility", CommentVisibility.PUBLIC.value))
            # Templated like every other body of text an automation writes. It
            # was the one that was not, so `{{actor.name}}` in a comment posted
            # the literal braces — the token panel offers it and the field
            # silently ignored it.
            comment = CommentCreate(body=text(params["body"]), visibility=visibility)
            return _Plan(PlanKind.COMMENT, f"add_comment ({visibility.value})", comment=comment)
    return _Plan(PlanKind.SKIP, f"unknown action {action_type}")  # pragma: no cover
