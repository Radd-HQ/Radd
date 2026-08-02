"""Creating the real Radd targets a plan names (spec 100), before any issue moves.

This is the "create the schema locally before importing, so I have real targets I
can commit to" step. Spec 90 only ever VALIDATED a create-mapping; the field did
not exist until the import was already running, so there was nothing to look at
and nothing to change your mind about.

Idempotent and re-runnable: everything is find-or-create, so provisioning twice
is a no-op and a plan can be edited and re-provisioned. Every creation is
ledgered, so rollback can remove the schema too.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import service as auth_service
from radd.modules.auth.types import UserSource
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate, FieldDefinitionUpdate
from radd.modules.fields.types import FieldSource, FieldType
from radd.modules.itemtypes import service as itemtypes_service
from radd.modules.itemtypes.schemas import IssueTypeCreate
from radd.modules.linktypes import service as linktypes_service
from radd.modules.linktypes.schemas import LinkTypeCreate
from radd.modules.linktypes.types import LinkDirection
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import enablement as timelog_enablement
from radd.modules.workflow import service as workflow_service
from radd.modules.workflow.schemas import StateCreate

from . import ledger
from .models import JiraPlan
from .plan.schemas import PlanMappings
from .types import (
    FieldAction,
    FieldScope,
    LedgerEntity,
    Problem,
    ProblemKind,
    UserAction,
    VocabAction,
)


@dataclass
class Provisioned:
    """The real ids everything downstream resolves against."""

    project_id: uuid.UUID | None = None
    field_keys: set[str] = field(default_factory=set)
    state_ids: dict[str, uuid.UUID] = field(default_factory=dict)  # Jira status → state
    type_ids: dict[str, uuid.UUID] = field(default_factory=dict)  # Jira type → issue type
    user_ids: dict[str, uuid.UUID] = field(default_factory=dict)  # Jira user key → user
    link_type_keys: set[str] = field(default_factory=set)
    problems: list[Problem] = field(default_factory=list)
    created: dict[str, int] = field(default_factory=dict)

    def _bump(self, key: str) -> None:
        self.created[key] = self.created.get(key, 0) + 1


async def run(
    session: AsyncSession,
    plan: JiraPlan,
    mappings: PlanMappings,
    *,
    run_id: uuid.UUID | None,
    placeholder_domain: str,
    commit: bool,
) -> Provisioned:
    """Create (or find) everything the plan names.

    `commit=False` resolves what already exists and REPORTS what would be created
    without writing — that is what makes the dry run able to say "3 fields and 2
    states will be created" truthfully.
    """
    out = Provisioned()
    out.project_id = await _project(session, plan, run_id, commit, out)
    await _fields(session, mappings, out.project_id, run_id, commit, out)
    await _link_types(session, mappings, run_id, commit, out)
    if out.project_id is not None:
        await _states(session, mappings, out.project_id, run_id, commit, out)
        await _issue_types(session, mappings, out.project_id, run_id, commit, out)
        if commit:
            # Worklogs 409 unless time logging is on for the project.
            await timelog_enablement.set_enabled(session, out.project_id, True)
    await _users(session, mappings, run_id, placeholder_domain, commit, out)
    return out


async def _project(
    session: AsyncSession,
    plan: JiraPlan,
    run_id: uuid.UUID | None,
    commit: bool,
    out: Provisioned,
) -> uuid.UUID | None:
    """Find the target project by key, else create it. Reusing an existing one is
    what lets a re-import top up a partially imported project."""
    for project in await projects_service.list_projects(session):
        if project.key.upper() == plan.radd_project_key.upper():
            return project.id
    if not commit:
        out._bump("projects")
        # A stand-in, so the dry run can go on to resolve and report every issue
        # rather than stopping at "there is no project yet".
        return uuid.uuid4()
    created = await projects_service.create_project(
        session,
        ProjectCreate(key=plan.radd_project_key.upper(), name=plan.radd_project_name),
    )
    await session.flush()
    if run_id:
        ledger.created(session, run_id, LedgerEntity.PROJECT, created.id, subject=created.key)
    out._bump("projects")
    return created.id


async def _fields(
    session: AsyncSession,
    mappings: PlanMappings,
    project_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    commit: bool,
    out: Provisioned,
) -> None:
    definitions = await fields_service.list_fields(session)
    by_key = {d.key: d for d in definitions}
    out.field_keys = set(by_key)
    # A field can exist but be SCOPED to other projects, in which case writing it
    # here fails with "unknown field" on every single issue. Widen the scope so
    # the target the plan names is a target that actually works.
    await _widen_scope(session, mappings, by_key, project_id, run_id, commit, out)
    await _extend_options(session, mappings, by_key, run_id, commit, out)
    for entry in mappings.fields:
        if entry.action is not FieldAction.CREATE or entry.target_key in out.field_keys:
            continue
        if not commit:
            out._bump("fields")
            out.field_keys.add(entry.target_key)
            continue
        # A value-remapped select's options are the TARGET values, not the raw ones.
        options = entry.create_options
        if entry.value_map and options:
            options = sorted({entry.value_map.get(o, o) for o in options})
        scoped = entry.create_scope is FieldScope.PROJECT and project_id is not None
        try:
            created = await fields_service.create_field(
                session,
                FieldDefinitionCreate(
                    project_ids=[project_id] if scoped else [],
                    key=entry.target_key,
                    name=entry.create_name or entry.target_key,
                    type=entry.create_type or FieldType.TEXT,
                    options=options,
                    source=FieldSource.USER,
                ),
            )
            await session.flush()
            if run_id:
                ledger.created(
                    session, run_id, LedgerEntity.FIELD, created.id, subject=entry.target_key
                )
            out.field_keys.add(entry.target_key)
            out._bump("fields")
        except Exception as exc:  # noqa: BLE001 — one bad field must not sink the rest
            out.problems.append(
                Problem(
                    kind=ProblemKind.PROVISION_FAILED,
                    message="a custom field could not be created",
                    subject=entry.target_key,
                    detail=str(exc),
                )
            )


async def _widen_scope(
    session: AsyncSession,
    mappings: PlanMappings,
    by_key: dict[str, object],
    project_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    commit: bool,
    out: Provisioned,
) -> None:
    """Bring every MAPPED field into scope for the target project.

    Radd scopes a custom field to zero projects (global) or to a named set. An
    earlier import can easily have scoped `site` to DEV — and then mapping into it
    from a new project fails per issue with "unknown field", which is exactly what
    a real 126-issue import hit. Widening is additive: the field keeps every
    project it already had, and the change is ledgered so rollback restores it.
    """
    if project_id is None:
        return
    for entry in mappings.fields:
        if entry.action is not FieldAction.MAP:
            continue
        definition = by_key.get(entry.target_key)
        scope = list(getattr(definition, "project_ids", []) or []) if definition else []
        if not definition or not scope or project_id in scope:
            continue  # missing (validation catches it), already global, or in scope
        if not commit:
            out._bump("fields_widened")
            continue
        try:
            if run_id:
                ledger.updated(
                    session,
                    run_id,
                    LedgerEntity.FIELD,
                    definition.id,
                    {"project_ids": [str(p) for p in scope]},
                    subject=entry.target_key,
                )
            await fields_service.update_field(
                session,
                definition.id,
                FieldDefinitionUpdate(project_ids=[*scope, project_id]),
                actor_id=None,
            )
            out._bump("fields_widened")
        except Exception as exc:  # noqa: BLE001
            out.problems.append(
                Problem(
                    kind=ProblemKind.PROVISION_FAILED,
                    message="a mapped field could not be brought into scope for this project",
                    subject=entry.target_key,
                    detail=str(exc),
                )
            )


async def _extend_options(
    session: AsyncSession,
    mappings: PlanMappings,
    by_key: dict[str, object],
    run_id: uuid.UUID | None,
    commit: bool,
    out: Provisioned,
) -> None:
    """Add the option values a mapped select is missing, where the plan says to.

    Additive only — every existing option survives, so no item already holding one
    becomes invalid. The previous list is ledgered, so rollback puts the field
    back exactly as it was. Without this, a value outside the target's options is
    simply dropped: on a live import that silently cost three show codes across
    seven issues.
    """
    for entry in mappings.fields:
        if entry.action is not FieldAction.MAP or not entry.extend_options:
            continue
        definition = by_key.get(entry.target_key)
        if definition is None:
            continue
        current = list(getattr(definition, "options", None) or [])
        if not current:
            continue  # not a select, or unconstrained — nothing to extend
        known = {v.casefold() for v in current}
        missing = [v for v in entry.observed_values if v and v.casefold() not in known]
        if not missing:
            continue
        if not commit:
            out._bump("options_added")
            continue
        try:
            if run_id:
                ledger.updated(
                    session,
                    run_id,
                    LedgerEntity.FIELD,
                    definition.id,
                    {"options": current},
                    subject=entry.target_key,
                )
            added = await fields_service.extend_options(
                session, definition.id, missing, actor_id=None
            )
            for _ in added:
                out._bump("options_added")
        except Exception as exc:  # noqa: BLE001
            out.problems.append(
                Problem(
                    kind=ProblemKind.PROVISION_FAILED,
                    message="missing options could not be added to a mapped field",
                    subject=entry.target_key,
                    detail=str(exc),
                    section="fields",
                    mapping_key=entry.target_key,
                )
            )


# A deterministic colour per issue-type name — Radd requires one and Jira has none.
_TYPE_COLOURS = ("#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#a855f7", "#14b8a6")


def _colour_for(name: str) -> str:
    return _TYPE_COLOURS[sum(ord(c) for c in name) % len(_TYPE_COLOURS)]


async def _states(
    session: AsyncSession,
    mappings: PlanMappings,
    project_id: uuid.UUID,
    run_id: uuid.UUID | None,
    commit: bool,
    out: Provisioned,
) -> None:
    """One Radd state per mapped Jira status, in the CATEGORY the plan chose —
    which is how "Rejected" finally lands in `canceled` instead of `todo`."""
    states = await workflow_service.list_states(session, project_id)
    by_name = {s.name.strip().lower(): s for s in states}
    for entry in mappings.statuses:
        if entry.action is VocabAction.IGNORE:
            continue
        name = (entry.state_name or entry.jira).strip()
        if not name:
            continue
        existing = by_name.get(name.lower())
        if existing is not None:
            out.state_ids[entry.jira] = existing.id
            continue
        if not commit:
            # A dry run must still RESOLVE, or every issue would report "no state"
            # and the preview would be a wall of false failures. A synthetic id
            # stands in for the row that would be created.
            out.state_ids[entry.jira] = uuid.uuid4()
            out._bump("states")
            continue
        try:
            created = await workflow_service.create_state(
                session,
                StateCreate(project_id=project_id, name=name[:100], category=entry.category),
            )
            await session.flush()
            if run_id:
                ledger.created(
                    session, run_id, LedgerEntity.STATE, created.id, subject=entry.jira
                )
            by_name[name.lower()] = created
            out.state_ids[entry.jira] = created.id
            out._bump("states")
        except Exception as exc:  # noqa: BLE001
            out.problems.append(
                Problem(
                    kind=ProblemKind.PROVISION_FAILED,
                    message="a workflow state could not be created",
                    subject=entry.jira,
                    detail=str(exc),
                )
            )


async def _issue_types(
    session: AsyncSession,
    mappings: PlanMappings,
    project_id: uuid.UUID,
    run_id: uuid.UUID | None,
    commit: bool,
    out: Provisioned,
) -> None:
    types = await itemtypes_service.list_types(session, project_id)
    by_name = {t.name.strip().lower(): t for t in types}
    for entry in mappings.issue_types:
        if entry.action is VocabAction.IGNORE:
            continue
        name = (entry.type_name or entry.jira).strip()
        if not name:
            continue
        existing = by_name.get(name.lower())
        if existing is not None:
            out.type_ids[entry.jira] = existing.id
            continue
        if not commit:
            out.type_ids[entry.jira] = uuid.uuid4()
            out._bump("issue_types")
            continue
        try:
            created = await itemtypes_service.create_type(
                session,
                IssueTypeCreate(
                    project_id=project_id,
                    name=name[:100],
                    # A stable colour per name, so re-provisioning is idempotent and
                    # two projects imported from the same Jira agree on the chip.
                    color=_colour_for(name),
                ),
            )
            await session.flush()
            if run_id:
                ledger.created(
                    session, run_id, LedgerEntity.ISSUE_TYPE, created.id, subject=entry.jira
                )
            by_name[name.lower()] = created
            out.type_ids[entry.jira] = created.id
            out._bump("issue_types")
        except Exception as exc:  # noqa: BLE001
            out.problems.append(
                Problem(
                    kind=ProblemKind.PROVISION_FAILED,
                    message="an issue type could not be created",
                    subject=entry.jira,
                    detail=str(exc),
                )
            )


async def _link_types(
    session: AsyncSession,
    mappings: PlanMappings,
    run_id: uuid.UUID | None,
    commit: bool,
    out: Provisioned,
) -> None:
    """Spec 91 made link types definable, so a Jira type Radd has never heard of
    becomes a real one instead of being flattened into `relates`."""
    catalog = await linktypes_service.catalog(session)
    out.link_type_keys = set(catalog)
    for entry in mappings.link_types:
        if entry.action is not VocabAction.CREATE or entry.key in out.link_type_keys:
            continue
        if not commit:
            out._bump("link_types")
            out.link_type_keys.add(entry.key)
            continue
        try:
            created = await linktypes_service.create_type(
                session,
                LinkTypeCreate(
                    key=entry.key,
                    name=entry.jira[:60],
                    outward_name=(entry.outward_name or entry.jira)[:60],
                    inward_name=(entry.inward_name or entry.jira)[:60],
                    direction=LinkDirection.DIRECTED,
                ),
            )
            await session.flush()
            if run_id:
                ledger.created(
                    session, run_id, LedgerEntity.LINK_TYPE, created.id, subject=entry.jira
                )
            out.link_type_keys.add(entry.key)
            out._bump("link_types")
        except Exception as exc:  # noqa: BLE001
            out.problems.append(
                Problem(
                    kind=ProblemKind.PROVISION_FAILED,
                    message="a link type could not be created",
                    subject=entry.jira,
                    detail=str(exc),
                )
            )


async def _users(
    session: AsyncSession,
    mappings: PlanMappings,
    run_id: uuid.UUID | None,
    placeholder_domain: str,
    commit: bool,
    out: Provisioned,
) -> None:
    """Resolve every person to a real Radd user id, per the plan's decision.

    Spec 90 had exactly one behaviour — invent an address on a hardcoded domain
    and create the account. Here MATCH/FALLBACK reuse an existing user, SKIP
    leaves the work unattributed, and PLACEHOLDER creates an account at an address
    the admin has already seen on the Users step.
    """
    by_email = {u.email.lower(): u.id for u in await auth_service.list_users(session)}
    for entry in mappings.users:
        if entry.action is UserAction.SKIP:
            continue
        if entry.action in (UserAction.MATCH, UserAction.FALLBACK):
            if entry.user_id is not None:
                out.user_ids[entry.jira_key] = entry.user_id
            continue
        email = (entry.placeholder_email or "").strip().lower()
        if not email:
            out.problems.append(
                Problem(
                    kind=ProblemKind.USER_UNRESOLVED,
                    message="no address for this person — their work will be unattributed",
                    subject=entry.display_name or entry.jira_key,
                )
            )
            continue
        if (existing := by_email.get(email)) is not None:
            out.user_ids[entry.jira_key] = existing
            continue
        if not commit:
            out.user_ids[entry.jira_key] = uuid.uuid4()
            out._bump("users")
            continue
        try:
            user, created_now = await auth_service.ensure_imported_user(
                session,
                email=email,
                name=entry.display_name or entry.jira_key,
                source=UserSource.JIRA,
            )
            await session.flush()
            if created_now and run_id:
                ledger.created(
                    session, run_id, LedgerEntity.USER, user.id, subject=entry.jira_key
                )
            by_email[email] = user.id
            out.user_ids[entry.jira_key] = user.id
            if created_now:
                out._bump("users")
        except Exception as exc:  # noqa: BLE001
            out.problems.append(
                Problem(
                    kind=ProblemKind.PROVISION_FAILED,
                    message="a placeholder account could not be created",
                    subject=entry.display_name or entry.jira_key,
                    detail=str(exc),
                )
            )
