import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import false, select

from radd.exceptions import ForbiddenError
from radd.kernel.registry import register_relation, register_row_guard
from radd.kernel.specs import RelationSpec, RowGuardSpec
from radd.modules.access import resolution as access_res, service as access_service
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.projects.models import Project

from ..enums import ItemVisibility
from ..models import WorkItem
from ..schemas import ItemRead

# --- relations (RADD-823): what @own / @team MEAN for an item -----------------
#
# D6: `@own` is the REPORTER — it survives imports (Jira's reporter maps
# straight across), a form filed on someone's behalf belongs to THEM, and
# reporter is reassignable so ownership can be handed over deliberately. A
# separate `@created` is not built until something needs it.
# D13: `@team` is `item.team_id` — the item's own team, nothing inferred. "The
# reporter's team when the item has none" would be a SECOND relation
# (`@reporter_team`), never a fuzzier definition of this one.
#
# Both forms per relation, mandatory (RelationSpec has no defaults): `where`
# is what keeps lists/counts/search honest, `holds` gates a loaded row. The
# contract test in tests/test_relation_semantics.py asserts the pair agrees.

ITEM_RELATIONS: tuple[RelationSpec, ...] = (
    RelationSpec(
        resource="item",
        key="own",
        label="they reported",
        where=lambda actor: WorkItem.reporter_id == actor.user_id,
        holds=lambda actor, item: item.reporter_id == actor.user_id,
    ),
    RelationSpec(
        resource="item",
        key="assigned",
        label="assigned to them",
        # Off the any⊃team⊃own chain: incomparable with team/own (an item
        # assigned to me is neither necessarily mine nor my team's), covered
        # only by @any.
        where=lambda actor: WorkItem.assignee_id == actor.user_id,
        holds=lambda actor, item: item.assignee_id == actor.user_id,
    ),
    RelationSpec(
        resource="item",
        key="team",
        label="on their team",
        # An actor with no teams matches nothing — false(), never IN (empty).
        where=lambda actor: (
            WorkItem.team_id.in_(actor.team_ids) if actor.team_ids else false()
        ),
        holds=lambda actor, item: item.team_id is not None and item.team_id in actor.team_ids,
    ),
    # Spec 121: `@public` is a property of the ROW, not of who the actor is —
    # the issue's own visibility. Off the chain like @assigned. `row_property`
    # is what makes holding `item.read@public` on a project ENTITLE the actor
    # to the project (it appears in their rail with no relationship needed).
    RelationSpec(
        resource="item",
        key="public",
        label="marked public",
        where=lambda actor: WorkItem.visibility == ItemVisibility.PUBLIC.value,
        holds=lambda actor, item: item.visibility == ItemVisibility.PUBLIC.value,
        row_property=True,
    ),
)

#: Spec 121: the relations that ADMIT a reader to a RESTRICTED issue — the
#: people on it. Resolved through the registry at query time, so an unloaded
#: participants plugin simply does not admit. Not @team (D13's "the item's
#: team" is a routing fact, not a confidence), not project.manage (D1).
RESTRICTED_ADMITS: tuple[str, ...] = ("own", "assigned", "participant")

#: Spec 121: the per-row admission EVERY item reader passes, whatever
#: relation they hold. `@any` stops meaning "every row" the moment this is
#: registered: an unqualified reader sees public + internal rows and the
#: restricted ones they are on; a `@public` reader sees public rows only
#: (public rows are never restricted, so the guard is moot for them).
ITEM_ROW_GUARD = RowGuardSpec(
    resource="item",
    label="restricted issues admit only the people on them",
    open_where=lambda: WorkItem.visibility != ItemVisibility.RESTRICTED.value,
    open_holds=lambda item: item.visibility != ItemVisibility.RESTRICTED.value,
    admits=RESTRICTED_ADMITS,
)

# Registered at import for direct-import contexts (unit tests, scripts) AND
# listed on the plugin manifest — the loader's clear() wipes import-time
# registrations, and the manifest is what survives it (the cascades precedent).
for _spec in ITEM_RELATIONS:
    register_relation(_spec)
register_row_guard(ITEM_ROW_GUARD)


async def relation_read_clause(
    session: AsyncSession,
    actor: User,
    permissions_by_project: "dict[uuid.UUID, frozenset[Permission]]",
):
    """THE row filter (RADD-817): per readable project, the actor's `item.read`
    relations compiled into one WHERE clause. None = unconstrained everywhere —
    the common case (`@any` held on every project), costing two set lookups per
    project and NO relation-actor resolution.

    Relations are per-PROJECT facts (a role granting `item.read@team` on one
    project says nothing about another), so the clause is an OR of per-project
    arms: unconstrained projects pass by project_id alone; a constrained
    project ANDs its relation filter in. Every shared builder applies this —
    lists, boards, reports, counts, bulk, MCP — or none do (the trap)."""
    from sqlalchemy import and_, or_

    constrained: dict[uuid.UUID, Any] = {}
    relation_actor = None
    # Spec 121: the row guard binds every non-admin reader, so `@any` is only
    # "unconstrained" when no guard applies — `relation_filter` answers None
    # in exactly that case, and the fast path below still costs nothing when
    # it does (the actor is resolved once, memoised).
    for project_id, permissions in permissions_by_project.items():
        relations = authz.relations_held(permissions, Permission.ITEM_READ)
        if relation_actor is None:
            relation_actor = await authz.relation_actor(session, actor)
        clause = authz.relation_filter("item", relations, relation_actor)
        if clause is None:
            continue
        constrained[project_id] = clause
    if not constrained:
        return None
    arms = []
    unconstrained = [pid for pid in permissions_by_project if pid not in constrained]
    if unconstrained:
        arms.append(WorkItem.project_id.in_(unconstrained))
    for project_id, clause in constrained.items():
        arms.append(and_(WorkItem.project_id == project_id, clause))
    return arms[0] if len(arms) == 1 else or_(*arms)


async def attach_capabilities(
    session: AsyncSession,
    actor: User,
    reads: "list[ItemRead]",
    rows_by_id: "dict[uuid.UUID, WorkItem]",
    permissions_by_project: "dict[uuid.UUID, frozenset[Permission]]",
) -> "list[ItemRead]":
    """Stamp the actor's per-row verdict onto API-bound reads (RADD-842).

    Cheap per row once the relation actor is resolved (memoised); a
    relation-qualified atom whose relation is query-gated (@participant,
    RADD-844) costs ONE batched membership query per (permission, page), never
    one per row. Rows whose backing WorkItem is unavailable keep
    capabilities=None, which the client reads as \"fall back to the
    project-level answer\"."""
    from .. import schemas

    relation_actor = None

    async def _holding_ids(permission: Permission) -> "dict[uuid.UUID, bool] | None":
        """None = unconstrained (@any everywhere the base atom is held);
        otherwise row.id -> verdict for every row whose project holds the base."""
        nonlocal relation_actor
        constrained_rows: list[WorkItem] = []
        for read in reads:
            permissions = permissions_by_project.get(read.project_id)
            row = rows_by_id.get(read.id)
            if row is None or permissions is None or not authz.holds_base(permissions, permission):
                continue
            if authz.RELATION_ANY not in authz.relations_held(permissions, permission):
                constrained_rows.append(row)
        if not constrained_rows:
            return None
        if relation_actor is None:
            relation_actor = await authz.relation_actor(session, actor)
        # The union of per-project relation sets is safe here only as an upper
        # bound would NOT be — so resolve per row against ITS project's set.
        verdicts: dict[uuid.UUID, bool] = {}
        by_relations: dict[frozenset, list[WorkItem]] = {}
        for row in constrained_rows:
            permissions = permissions_by_project[row.project_id]
            by_relations.setdefault(
                authz.relations_held(permissions, permission), []
            ).append(row)
        for relations, rows in by_relations.items():
            held = await authz.relation_row_ids_holding(
                session, "item", relations, relation_actor, rows
            )
            for row in rows:
                verdicts[row.id] = row.id in held
        return verdicts

    update_verdicts = await _holding_ids(Permission.ITEM_UPDATE)
    comment_verdicts = await _holding_ids(Permission.COMMENT_WRITE)

    out: list[ItemRead] = []
    for read in reads:
        row = rows_by_id.get(read.id)
        permissions = permissions_by_project.get(read.project_id)
        if row is None or permissions is None:
            out.append(read)
            continue
        can_update = authz.holds_base(permissions, Permission.ITEM_UPDATE)
        if can_update and update_verdicts is not None:
            can_update = update_verdicts.get(read.id, True)
        can_comment = authz.holds_base(permissions, Permission.COMMENT_WRITE)
        if can_comment and comment_verdicts is not None:
            can_comment = comment_verdicts.get(read.id, True)
        out.append(
            read.model_copy(
                update={
                    "capabilities": schemas.ItemCapabilities(
                        can_update=can_update,
                        can_transition=can_update,
                        can_comment=can_comment,
                    )
                }
            )
        )
    return out


async def ensure_item_relation(
    session: AsyncSession,
    actor: User,
    item: "WorkItem",
    permissions: frozenset[Permission],
    permission: Permission,
    *,
    as_missing: bool = False,
) -> None:
    """The GATING form (RADD-817): the caller's atom is held (require passed) —
    does it hold for THIS row? `@any` short-circuits free. A failed READ raises
    NotFound (`as_missing=True` — a hidden item's existence stays private, the
    spec-57 rule); a failed write raises Forbidden naming the qualifier."""
    relations = authz.relations_held(permissions, permission)
    relation_actor = await authz.relation_actor(session, actor)
    # async form (RADD-844): honours query-gated relations (@participant) with
    # one EXISTS; pure predicates still answer free. Spec 121: `@any` no
    # longer short-circuits HERE — the primitive applies the row guard first
    # and answers True for @any only past it.
    if await authz.relation_holds_row_async(session, "item", relations, relation_actor, item):
        return
    if as_missing:
        from radd.exceptions import NotFoundError

        from ..enums import ItemEntity

        raise NotFoundError(ItemEntity.ITEM, item.id)
    held = ", ".join(sorted(f"@{r}" for r in relations))
    raise ForbiddenError(
        f"'{permission}' is limited to {held} here, and this is not such an item"
    )

# --- field-level visibility (spec 07: per-role/team grants) ---


# A read-restricted builtin field (spec 50) is blanked out of the representation
# for non-granted principals. Only fields in READ_RESTRICTABLE_BUILTINS appear here
# (title/state/priority are never restrictable — see fields.types).
_BLANK_BUILTIN: dict[str, dict[str, Any]] = {
    "description": {"description": ""},
    "assignee": {"assignee": None},
    "reporter": {"reporter": None},
    "team": {"team": None},
    "parent": {"parent": None},
    "start_date": {"start_date": None},
    "target_date": {"target_date": None},
    "cycle": {"cycle": None},
    "release": {"release": None},
    "labels": {"labels": []},
    "flagged": {"flagged": False},
    "estimate_points": {"estimate_points": None},
}


def _filter_read(
    read: ItemRead,
    definitions: Sequence[FieldDefinition],
    ctx: fields.FieldAccessContext,
    builtin_denied: Sequence[str] = (),
) -> ItemRead:
    """Drop custom_fields the actor may not see and blank read-restricted builtin
    fields (spec 07 + 50)."""
    allowed = fields.readable_keys(definitions, ctx)
    update: dict[str, Any] = {
        "custom_fields": {k: v for k, v in read.custom_fields.items() if k in allowed}
    }
    for field in builtin_denied:
        update.update(_BLANK_BUILTIN.get(field, {}))
    return read.model_copy(update=update)


async def _builtin_read_denied(
    session: AsyncSession, project: Project, ctx: fields.FieldAccessContext
) -> list[str]:
    """Builtin fields this actor may not read on the project (spec 50/92). The read
    grants + subjects were resolved into `ctx` by `_field_ctx` — cheap no-op for the
    common case (manage holder, or no read grants in scope)."""
    # `ctx.has_manage` = INSTANCE ADMIN since RADD-816 — a restricted builtin
    # blanks for a project MANAGER now unless a grant names them.
    if ctx.has_manage or not any(ctx.builtin_grants.values()):
        return []
    return fields.builtin_read_denied(ctx.builtin_grants, ctx.as_subject(), ctx.project_id)


# ItemCreate/ItemUpdate attribute -> the BuiltinItemField it writes (spec 36 rules).
_BUILTIN_FIELD_MAP: dict[str, str] = {
    "title": "title",
    "description": "description",
    "state_id": "state",
    "priority": "priority",
    "assignee_id": "assignee",
    "reporter_id": "reporter",
    "team_id": "team",
    "labels": "labels",
    "parent_id": "parent",
    "start_date": "start_date",
    "target_date": "target_date",
    "cycle_id": "cycle",
    "release_id": "release",
    "flagged": "flagged",
    "estimate_points": "estimate_points",
}


async def _check_builtin_field_rules(
    session: AsyncSession,
    actor: User,
    project: Project,
    permissions: frozenset[Permission],
    fields_set: frozenset[str] | set[str],
) -> None:
    """Spec 36: builtin fields default write-open, but a rule row restricts a
    field to its role/team subjects (project.manage always passes). 403 names
    the denied fields, mirroring the custom-field grant message."""
    touched = {_BUILTIN_FIELD_MAP[key] for key in fields_set if key in _BUILTIN_FIELD_MAP}
    if not touched:
        return
    grants = await access_service.grants_for_resources(
        session, fields.BUILTIN_RESOURCE, sorted(touched)
    )
    if not any(grants.values()):
        return
    subjects = await authz.subjects_for(session, actor, project)
    subject = access_res.SubjectContext(
        user_id=actor.id,
        role_ids=subjects.role_ids,
        team_ids=subjects.team_ids,
        group_ids=subjects.group_ids,
        # RADD-816: instance admin, NOT project.manage — the bypass demotion.
        has_manage=await authz.is_admin(session, actor),
    )
    denied = fields.builtin_write_denied(sorted(touched), grants, subject, project.id)
    if denied:
        raise ForbiddenError("no permission to write fields: " + ", ".join(denied))


async def _field_ctx(
    session: AsyncSession,
    actor: User,
    project: Project,
    permissions: frozenset[Permission],
    definitions: Sequence[FieldDefinition],
) -> fields.FieldAccessContext:
    """The actor's field-grant context (spec 92): the fields' access grants + the
    actor's per-project subjects. Batch-loads grants and skips the subject lookup
    when no field in the project carries any grant (the common case)."""
    has_manage = await authz.is_admin(session, actor)  # RADD-816: admin, not pm

    async def _subjects() -> tuple[
        frozenset[uuid.UUID], frozenset[uuid.UUID], frozenset[uuid.UUID]
    ]:
        subjects = await authz.subjects_for(session, actor, project)
        return subjects.role_ids, subjects.team_ids, subjects.group_ids

    return await fields.build_field_ctx(
        session,
        definitions,
        project,
        user_id=actor.id,
        has_manage=has_manage,
        subjects_lookup=_subjects,
    )


def _internal_visible(
    permissions_by_project: dict[uuid.UUID, frozenset[Permission]],
) -> set[uuid.UUID]:
    """Projects where the actor may see internal comments (visible-only comment_count)."""
    return {
        pid
        for pid, permissions in permissions_by_project.items()
        if Permission.COMMENT_READ_INTERNAL in permissions
    }


# Read-restrictable builtin -> the SLQ field names that disclose its value
# (RADD-840). `parent` restriction hides WHO the ancestors are, so every
# ancestor field goes with it; assignee restriction covers its ancestor
# mirrors. description has no SLQ field; title/state/priority are never
# read-restrictable.
_BUILTIN_TO_SLQ_FIELDS: dict[str, tuple[str, ...]] = {
    "assignee": ("assignee", "epic.assignee", "parent.assignee"),
    "reporter": ("reporter",),
    "team": ("team",),
    "labels": ("label",),
    "parent": (
        "parent",
        "epic",
        "epic.state",
        "epic.category",
        "epic.assignee",
        "epic.priority",
        "parent.state",
        "parent.category",
        "parent.assignee",
        "parent.priority",
    ),
    "start_date": ("start",),
    "target_date": ("target",),
    "cycle": ("cycle", "cycle.status", "past_cycle"),
    "release": ("release",),
    "flagged": ("flagged",),
    "estimate_points": ("points",),
}


async def denied_slq_fields(
    session: AsyncSession, actor: User, project: Project | None
) -> frozenset[str]:
    """SLQ field names + custom keys this actor may not filter or sort by
    (RADD-840): anything the compiler will match against is disclosable by
    bisection, and /items/count makes the oracle cheap — so the grant check
    lives at compile time, exactly like an unknown field.

    With a project: the exact per-actor resolution the read path uses. Without
    one (cross-project surfaces): conservative — any field carrying a
    read-restricting grant anywhere is denied for everyone except an instance
    admin, since per-project subjects can't be resolved for a query that spans
    them all. Restriction is rare; a leak is not.
    """

    if authz.is_instance_admin(actor):
        return frozenset()

    denied: set[str] = set()
    if project is not None:
        permissions = await authz.effective_permissions(session, actor, project=project)
        definitions = await fields.definitions_for_project(session, project)
        ctx = await _field_ctx(session, actor, project, permissions, definitions)
        denied |= {d.key for d in definitions} - fields.readable_keys(definitions, ctx)
        for name in await _builtin_read_denied(session, project, ctx):
            denied |= set(_BUILTIN_TO_SLQ_FIELDS.get(name, ()))
        return frozenset(denied)

    definitions = await fields.list_fields(session)
    field_grants = await access_service.grants_for_resources(
        session, fields.FIELD_RESOURCE, [str(d.id) for d in definitions]
    )
    for definition in definitions:
        if any(
            g.access == fields.Access.READ.value
            for g in field_grants.get(str(definition.id), ())
        ):
            denied.add(definition.key)
    builtin_grants = await access_service.grants_for_resources(
        session, fields.BUILTIN_RESOURCE, sorted(_BUILTIN_TO_SLQ_FIELDS)
    )
    for name, grants in builtin_grants.items():
        if any(g.access == fields.Access.READ.value for g in grants):
            denied |= set(_BUILTIN_TO_SLQ_FIELDS.get(name, ()))
    return frozenset(denied)


# --- project visibility (RADD-937) --------------------------------------------


async def projects_with_user_items(session: AsyncSession, user) -> set[uuid.UUID]:
    """Projects the actor personally has an item in — reported OR assigned.

    Half of the answer to "why can this person see this project without a grant
    on it". A qualified read (`item.read@own`) says they may read their own rows
    ANYWHERE, which the project list used to read as "every project"; requiring
    the relationship to be real is what turns that into the projects they
    actually work in.

    Kept as ONE query over the two columns rather than two: `work_items` indexes
    both, so the planner ORs the bitmaps and the whole thing is a 2.2 ms index
    scan over 503k rows — cheap enough to run per request, which is why this is
    resolved live instead of being materialised into a membership table that
    would then need keeping in step.
    """
    rows = await session.execute(
        select(WorkItem.project_id)
        .where((WorkItem.reporter_id == user.id) | (WorkItem.assignee_id == user.id))
        .distinct()
    )
    return set(rows.scalars())


async def projects_with_team_items(session: AsyncSession, user) -> set[uuid.UUID]:
    """Projects where one of the actor's TEAMS owns an item (`work_items.team_id`).

    The item's own team, nothing inferred — the same reading `@team` already has
    in the relation above, so "my team's work" means one thing across the
    codebase rather than two.
    """
    from radd.modules.teams import service as teams  # deferred: teams loads before items

    team_ids = await teams.user_team_ids(session, user.id)
    if not team_ids:
        return set()
    rows = await session.execute(
        select(WorkItem.project_id).where(WorkItem.team_id.in_(team_ids)).distinct()
    )
    return set(rows.scalars())
