import re
import uuid
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.access import service as access_service
from radd.modules.access.service import AccessGrant  # public re-export (RADD-887)
from radd.modules.access.registry import ResourceSpec, register_resource
from radd.modules.access.types import GrantEffect, GrantSubject
from radd.modules.auth import authz, service as users_service
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.fields.types import FieldType
from radd.modules.groups import service as groups_service
from radd.modules.items import service as items_service, slq
from radd.modules.items.filters import ItemFilterParam
from radd.modules.teams import service as teams_service
from radd.modules.workflow import service as workflow_service
from radd.modules.projects import service as projects_service

from .models import CardLayoutPreset, View, ViewMember
from .schemas import (
    CARD_GRID_COLS,
    _validate_bucket_order,
    CardLayout,
    CardPresetCreate,
    CardPresetUpdate,
    QuickFilter,
    ShareGroupRef,
    ShareTeamRef,
    ShareUserRef,
    ViewCreate,
    ViewRead,
    ViewShareEntry,
    ViewShareRead,
    ViewSharingUpdate,
    ViewTransfer,
    ViewUpdate,
)

from .types import (
    CF_AXIS_PREFIX,
    ShareLevel,
    ViewAxis,
    ViewEntity,
    ViewEvent,
)

# The one mandatory card cell (spec 109) — a card without its title is unusable.
CARD_TITLE_ATTR = "title"

# View shares are grants in the generic access framework (spec 92): resource_type
# "view", resource_id = the view id, subject user/team, access = a ShareLevel
# (hierarchical viewer<editor<owner), owner-CLOSED by default, NOT project-scoped
# (a view already belongs to one project). `global_access` + `owner_id` stay on
# the View row (a public level + the accountable owner — not per-subject grants).
VIEW_RESOURCE = "view"


# Personal use of views (create private, edit own) only needs item.read in scope;
# the view.* CRUD atoms gate server-wide broadcasts + seeded owner-less views.
PERSONAL_VIEW_PERMISSION = Permission.ITEM_READ


# --- sharing resolution (spec 57) ---


async def _shares_by_view(
    session: AsyncSession, view_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[AccessGrant]]:
    """The view-share grants (spec 92) grouped by view id (batch, no N+1)."""
    if not view_ids:
        return {}
    id_map = {str(v): v for v in view_ids}
    grants = await access_service.grants_for_resources(
        session, VIEW_RESOURCE, list(id_map)
    )
    return {id_map[rid]: rows for rid, rows in grants.items()}


def _grant_level(
    view: View,
    grants: list[AccessGrant],
    actor_id: uuid.UUID,
    team_ids: set[uuid.UUID],
    group_ids: set[uuid.UUID],
) -> ShareLevel | None:
    """The highest ShareLevel the actor holds on the view via direct/team/group
    grants or global_access — None = the view is invisible to them. `group_ids`
    is the TRANSITIVE closure (RADD-832), so a share with a parent group reaches
    nested members."""
    level = access_service.shared_resource_level(
        VIEW_RESOURCE, grants, user_id=actor_id, team_ids=team_ids,
        group_ids=group_ids, global_access=view.global_access,
    )
    return ShareLevel(level) if level is not None else None


async def _can_manage_view(
    session: AsyncSession, actor: User, resource_id: str, project_id: uuid.UUID | None
) -> bool:
    """Who may manage a view's share grants: the owner, a co-owner (OWNER-level
    grant), or — seeded owner-less views — a view.update holder in scope. Mirrors
    `_require_manage` for the generic /grants router."""
    try:
        view = await get_view(session, uuid.UUID(resource_id))
    except (ValueError, NotFoundError):
        return False
    try:
        await _require_scope(session, actor, PERSONAL_VIEW_PERMISSION, project_id=view.project_id)
    except ForbiddenError:
        return False
    if view.owner_id == actor.id:
        return True
    grant = (await _sharing_state(session, actor, [view.id]))[view.id][0]
    if grant is ShareLevel.OWNER:
        return True
    if view.owner_id is None:
        if view.project_id is not None:
            project = await projects_service.get_project(session, view.project_id)
            perms = await authz.effective_permissions(session, actor, project=project)
        else:
            perms = await authz.effective_permissions(session, actor)
        return Permission.VIEW_UPDATE in perms
    return False


async def _lock_view(session: AsyncSession, resource_id: str) -> None:
    try:
        resource_uuid = uuid.UUID(resource_id)
    except ValueError:
        raise NotFoundError(ViewEntity.VIEW, resource_id) from None
    row = await session.scalar(select(View).where(View.id == resource_uuid)
        .with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise NotFoundError(ViewEntity.VIEW, resource_id)


async def _view_labels(session: AsyncSession, resource_ids) -> dict[str, str]:
    """Inspector labels (RADD-809): view id -> name."""
    ids = [uuid.UUID(raw) for raw in resource_ids if _uuidish(raw)]
    if not ids:
        return {}
    rows = await session.execute(select(View.id, View.name).where(View.id.in_(ids)))
    return {str(view_id): name for view_id, name in rows.all()}


def _uuidish(raw: str) -> bool:
    try:
        uuid.UUID(raw)
    except ValueError:
        return False
    return True


_VIEW_SPEC = ResourceSpec(
    resource_type=VIEW_RESOURCE,
    can_manage=_can_manage_view,
    accesses=(ShareLevel.VIEWER.value, ShareLevel.EDITOR.value, ShareLevel.OWNER.value),
    default_open=False,  # a view is private (owner-only) until shared
    hierarchical=True,  # viewer < editor < owner — the effective level is the highest held
    subjects=(GrantSubject.USER, GrantSubject.TEAM, GrantSubject.GROUP),
    project_scoped=False,  # a view already belongs to one project
    label="View",
    label_for=_view_labels,
    lock_resource=_lock_view,
)
register_resource(_VIEW_SPEC)


async def _scope_permissions(
    session: AsyncSession,
    actor: User,
    view: View,
    cache: dict[uuid.UUID | None, frozenset[Permission]],
) -> frozenset[Permission]:
    """Effective permissions in the view's scope, cached per project across a batch."""
    key = view.project_id
    if key not in cache:
        if view.project_id is not None:
            project = await projects_service.get_project(session, view.project_id)
            cache[key] = await authz.effective_permissions(session, actor, project=project)
        else:
            cache[key] = await authz.effective_permissions(
                session, actor
            )
    return cache[key]


async def _hydrate(session: AsyncSession, actor: User, views: list[View], *, include_shares: bool = True) -> list[ViewRead]:
    """Batch-build reads: sharing state + per-ACTOR capabilities (spec 57).
    can_edit = definition writes; can_manage = sharing + delete (owner, or the
    view.update atom on SEEDED owner-less views)."""
    if not views:
        return []
    shares_map = await _shares_by_view(session, [v.id for v in views]) if include_shares else {}
    states = await _sharing_state(session, actor, [row.id for row in views]) if not include_shares else {}
    user_ids = {v.owner_id for v in views if v.owner_id is not None}
    team_ids: set[uuid.UUID] = set()
    group_ids: set[uuid.UUID] = set()
    for grants in shares_map.values():
        user_ids |= {g.subject_id for g in grants if g.subject_type == GrantSubject.USER.value}
        team_ids |= {g.subject_id for g in grants if g.subject_type == GrantSubject.TEAM.value}
        group_ids |= {g.subject_id for g in grants if g.subject_type == GrantSubject.GROUP.value}
    users = await users_service.users_by_ids(session, user_ids)
    teams = await teams_service.teams_by_ids(session, team_ids)
    groups = await groups_service.groups_by_ids(session, group_ids)
    actor_teams = await teams_service.user_team_ids(session, actor.id)
    actor_groups = await groups_service.user_group_ids(session, actor.id)
    perms_cache: dict[uuid.UUID | None, frozenset[Permission]] = {}

    reads: list[ViewRead] = []
    for view in views:
        shares = shares_map.get(view.id, [])
        # The legacy sharing editor reconciles positive shares. Deny rows are
        # policy, not invitations, and remain on the full generic grants API.
        allowed_shares = [g for g in shares if g.effect == GrantEffect.ALLOW]
        grant = (_grant_level(view, shares, actor.id, actor_teams, actor_groups) if include_shares
                 else states[view.id][0])
        if view.owner_id == actor.id or grant is ShareLevel.OWNER:
            can_manage = True
        elif view.owner_id is None:
            can_manage = Permission.VIEW_UPDATE in await _scope_permissions(
                session, actor, view, perms_cache
            )
        else:
            can_manage = False
        pairs: list[tuple[str, str]] = []
        if view.query:
            pairs.append((ItemFilterParam.Q.value, view.query))
        if view.project_id is not None:
            pairs.append((ItemFilterParam.PROJECT_ID.value, str(view.project_id)))
        owner = users.get(view.owner_id) if view.owner_id else None
        reads.append(
            ViewRead(
                id=view.id,
                project_id=view.project_id,
                name=view.name,
                # Pass the stored string through — a plugin view_type (spec 94) is
                # not a builtin `ViewType` member, so never coerce (it would raise).
                view_type=view.view_type,
                query=view.query,
                group_by=view.group_by,
                swimlane_by=view.swimlane_by,
                cycle_filter=view.cycle_filter,
                quick_filters=[
                    QuickFilter.model_validate(entry) for entry in view.quick_filters or []
                ],
                wip_limits=(
                    {uuid.UUID(key): limit for key, limit in view.wip_limits.items()}
                    if view.wip_limits
                    else None
                ),
                columns=view.columns,
                card_layout=(
                    CardLayout.model_validate(view.card_layout) if view.card_layout else None
                ),
                column_order=view.column_order,
                collapse_empty_columns=view.collapse_empty_columns,
                hidden_columns=view.hidden_columns,
                swimlane_order=view.swimlane_order,
                owner_id=view.owner_id,
                owner=ShareUserRef(id=owner.id, name=owner.name) if owner else None,
                global_access=ShareLevel(view.global_access)
                if view.global_access
                else None,
                shares=[
                    ViewShareRead(
                        id=g.id,
                        level=ShareLevel(g.access),
                        user=(
                            ShareUserRef(id=u.id, name=u.name)
                            if g.subject_type == GrantSubject.USER.value
                            and (u := users.get(g.subject_id))
                            else None
                        ),
                        team=(
                            ShareTeamRef(id=t.id, name=t.name)
                            if g.subject_type == GrantSubject.TEAM.value
                            and (t := teams.get(g.subject_id))
                            else None
                        ),
                        group=(
                            ShareGroupRef(id=grp.id, name=grp.name)
                            if g.subject_type == GrantSubject.GROUP.value
                            and (grp := groups.get(g.subject_id))
                            else None
                        ),
                    )
                    for g in allowed_shares
                ],
                shared=view.owner_id is None
                or view.global_access is not None
                or (len(allowed_shares) > 0 if include_shares else states[view.id][1]),
                can_edit=can_manage or grant in (ShareLevel.EDITOR, ShareLevel.OWNER),
                can_manage=can_manage,
                position=view.position,
                query_string=urlencode(pairs),
                created_at=view.created_at,
                updated_at=view.updated_at,
            )
        )
    return reads


async def _hydrate_one(session: AsyncSession, actor: User, view: View, *,
                         include_shares: bool = True) -> ViewRead:
    return (await _hydrate(session, actor, [view], include_shares=include_shares))[0]


async def _sharing_state(session, actor, ids):
    if not ids:
        return {}
    level, shared = await access_service.shared_resource_state_expressions(session, actor,
        VIEW_RESOURCE, resource_id=View.id, global_access=View.global_access)
    rows = await session.execute(select(View.id, level, shared).where(View.id.in_(ids)))
    return {row_id: (ShareLevel(value) if value else None, bool(has_shares))
            for row_id, value, has_shares in rows}



# --- SLQ + axis validation (spec 10) ---


async def _scope_definitions(
    session: AsyncSession, project_id: uuid.UUID | None
) -> dict[str, FieldDefinition]:
    """key -> definition for the view's scope: the project's registry when
    project-scoped, every definition globally otherwise (oldest wins)."""
    if project_id is not None:
        project = await projects_service.get_project(session, project_id)
        definitions = await fields.definitions_for_project(session, project)
    else:
        definitions = await fields.list_fields(session)
    by_key: dict[str, FieldDefinition] = {}
    for definition in definitions:
        by_key.setdefault(definition.key, definition)
    return by_key


async def _validate_query(
    session: AsyncSession, view: View, actor: User, query: str
) -> str:
    """Parse + compile against the view's scope registry -> SlqError (422 with
    position) on any problem. Names (states/teams/labels) resolve at query time."""
    text = query.strip()
    if text:
        definitions = await _scope_definitions(session, view.project_id)
        project = (
            await projects_service.get_project(session, view.project_id)
            if view.project_id
            else None
        )
        await slq.compile_query(
            session,
            slq.parse(text),
            definitions_by_key=definitions,
            current_user_id=actor.id,
            project_id=view.project_id,
            denied_fields=await items_service.denied_slq_fields(session, actor, project),
        )
    return text


_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


async def _validate_quick_filters(
    session: AsyncSession, view: View, actor: User, filters: list[QuickFilter]
) -> list[dict[str, str]]:
    """Each chip's SLQ must compile standalone AND stay a pure condition — active
    chips are parenthesized and AND-ed into the view query, where a nested ORDER BY
    would be a syntax error."""
    validated: list[dict[str, str]] = []
    for entry in filters:
        if _ORDER_BY_RE.search(entry.query):
            raise ConflictError(
                ViewEntity.VIEW,
                reason=f"quick filter '{entry.name}': ORDER BY is not allowed in a filter",
            )
        query = await _validate_query(session, view, actor, entry.query)
        validated.append({"name": entry.name, "query": query})
    return validated


def _validate_cycle_filter(pattern: str | None) -> str | None:
    """cycle_filter is a REGEX (spec 56, case-insensitive, unanchored) deciding
    which cycle headers a cycle-grouped view shows. Invalid patterns 409 here so
    the client never stores one it can't apply."""
    if not pattern:
        return None
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ConflictError(
            ViewEntity.VIEW, reason=f"cycle filter: invalid regex — {exc}"
        ) from exc
    return pattern


def _validate_columns(columns: list[str] | None) -> list[str] | None:
    """Spec 108 list columns: trimmed, deduped (order kept), empty = None. Ids
    are deliberately validated loosely (builtin name or `cf.<key>`) — a custom
    field can leave the registry at any time, and a stale id must degrade to an
    unknown column in the editor, not brick the view."""
    if not columns:
        return None
    cleaned = [entry for entry in dict.fromkeys(c.strip() for c in columns) if entry]
    for entry in cleaned:
        if len(entry) > 80:
            raise ConflictError(ViewEntity.VIEW, reason=f"column id too long: {entry[:80]}…")
    return cleaned or None


def _validate_card_layout(layout: CardLayout | None) -> dict[str, Any] | None:
    """Spec 109 card layout: shape (row/col/span bounds, cell cap) is
    pydantic-enforced (422); semantics land here (409). Attr IDS are deliberately
    validated loosely (the pydantic length cap only) — a departed custom field
    must degrade to an empty cell, not brick the view. None/no-cells = None =
    the view type's default card."""
    if layout is None or not layout.cells:
        return None
    attrs = [cell.attr for cell in layout.cells]
    duplicates = {attr for attr in attrs if attrs.count(attr) > 1}
    if duplicates:
        raise ConflictError(
            ViewEntity.VIEW,
            reason=f"card_layout: attribute placed twice — {', '.join(sorted(duplicates))}",
        )
    if CARD_TITLE_ATTR not in attrs:
        raise ConflictError(ViewEntity.VIEW, reason="card_layout: the title cell is mandatory")
    by_row: dict[int, list] = {}
    for cell in layout.cells:
        if cell.col + cell.span > CARD_GRID_COLS:
            raise ConflictError(
                ViewEntity.VIEW,
                reason=f"card_layout: '{cell.attr}' overflows the grid "
                f"(col {cell.col} + span {cell.span} > {CARD_GRID_COLS})",
            )
        by_row.setdefault(cell.row, []).append(cell)
    for row_cells in by_row.values():
        row_cells.sort(key=lambda c: c.col)
        for prev, cell in zip(row_cells, row_cells[1:]):
            if cell.col < prev.col + prev.span:
                raise ConflictError(
                    ViewEntity.VIEW,
                    reason=f"card_layout: '{prev.attr}' and '{cell.attr}' overlap in row {cell.row}",
                )
    return layout.model_dump()


async def _validate_wip_limits(
    session: AsyncSession, view: View, limits: dict[uuid.UUID, int] | None
) -> dict[str, int] | None:
    """Soft WIP limits (spec 76): value shape (int>=1) is pydantic-enforced (422);
    on a PROJECT-scoped view every key must be one of that project's state ids
    (409). All-projects boards bucket by state NAME, so any UUID key is
    stored as-is — a limit simply only displays where the bucket key matches."""
    if not limits:
        return None
    if view.project_id is not None:
        known = {state.id for state in await workflow_service.list_states(session, view.project_id)}
        for state_id in limits:
            if state_id not in known:
                raise ConflictError(
                    ViewEntity.VIEW,
                    reason=f"wip_limits: no state {state_id} in the view's project",
                )
    return {str(state_id): limit for state_id, limit in limits.items()}


async def _validate_axes(session: AsyncSession, view: View) -> None:
    """Axis tokens: builtins pass; `cf.<key>` must be a select-type registry field
    in scope (409); swimlane_by must differ from group_by (409). Token *shape* is
    already pydantic-enforced (422)."""
    definitions: dict[str, FieldDefinition] | None = None
    for axis in (view.group_by, view.swimlane_by):
        if axis is None or axis in set(ViewAxis):
            continue
        key = axis.removeprefix(CF_AXIS_PREFIX)
        if definitions is None:
            definitions = await _scope_definitions(session, view.project_id)
        definition = definitions.get(key)
        if definition is None:
            raise ConflictError(
                ViewEntity.VIEW, reason=f"axis '{axis}': no custom field '{key}' in scope"
            )
        if FieldType(definition.type) is not FieldType.SELECT:
            raise ConflictError(
                ViewEntity.VIEW,
                reason=f"axis '{axis}' must be a select field, not {definition.type}",
            )
    if view.group_by is not None and view.group_by == view.swimlane_by:
        raise ConflictError(
            ViewEntity.VIEW, reason=f"swimlane_by must differ from group_by ('{view.group_by}')"
        )


# --- scope + access ---


async def _require_scope(
    session: AsyncSession,
    actor: User,
    permission: Permission,
    *,
    project_id: uuid.UUID | None,
) -> None:
    """Enforce `permission` in the view's scope: its project, else across projects.

    An ALL-PROJECTS view has no single scope to check against, so a global-atom
    check was standing in for one — and a project-scoped grant never satisfies a
    global check (RADD-788). Holding the atom in any project is the honest bar for
    a view that spans them: the rows it returns are filtered per project anyway.
    """
    if project_id is not None:
        project = await projects_service.get_project(session, project_id)
        await authz.require(session, actor, permission, project=project)
    elif not await authz.require_anywhere(session, actor, permission):
        raise ForbiddenError(f"permission '{permission}' denied")


async def get_view(session: AsyncSession, view_id: uuid.UUID) -> View:
    view = await session.get(View, view_id)
    if view is None:
        raise NotFoundError(ViewEntity.VIEW, view_id)
    return view


async def _load_visible(
    session: AsyncSession, view_id: uuid.UUID, actor: User
) -> tuple[View, ShareLevel | None]:
    """The view + the actor's grant level; invisible views 404 (spec 57 —
    privacy over acknowledgment, admins included: not shared = not seen)."""
    view = await get_view(session, view_id)
    grant = (await _sharing_state(session, actor, [view.id]))[view.id][0]
    if view.owner_id != actor.id and grant is None:
        raise NotFoundError(ViewEntity.VIEW, view_id)
    return view, grant


async def visible_view(session: AsyncSession, view_id: uuid.UUID, actor: User) -> View:
    """The view iff the actor can SEE it (spec-57 visibility) — otherwise the
    read path's 404. Public seam for other modules: the dashboards module
    (spec 75) validates `view_count` widget references against it."""
    view, _ = await _load_visible(session, view_id, actor)
    return view


async def _require_edit(session: AsyncSession, view_id: uuid.UUID, actor: User) -> View:
    """Definition writes: the owner, an editor/owner-level grantee, or (LEGACY
    owner-less views) a view.update atom holder. Visible-but-viewer -> 403."""
    await _lock_view(session, str(view_id))
    view, grant = await _load_visible(session, view_id, actor)
    if view.owner_id == actor.id or grant in (ShareLevel.EDITOR, ShareLevel.OWNER):
        await _require_scope(
            session,
            actor,
            PERSONAL_VIEW_PERMISSION,
            project_id=view.project_id,
        )
        return view
    if view.owner_id is None:
        await _require_scope(
            session,
            actor,
            Permission.VIEW_UPDATE,
            project_id=view.project_id,
        )
        return view
    raise ForbiddenError("view is shared with you as a viewer — ask the owner for edit access")


async def _require_manage(
    session: AsyncSession, view_id: uuid.UUID, actor: User, *, legacy_atom: Permission
) -> View:
    """Sharing changes + delete + transfer: the owner or an OWNER-level grantee
    (co-owner) — editor grantees edit content, they don't re-share or delete.
    Seeded owner-less views fall back to the view.* RBAC atom (`legacy_atom`)."""
    await _lock_view(session, str(view_id))
    view, grant = await _load_visible(session, view_id, actor)
    await _require_scope(session, actor, PERSONAL_VIEW_PERMISSION, project_id=view.project_id)
    if view.owner_id == actor.id or grant is ShareLevel.OWNER:
        return view
    if view.owner_id is None:
        await _require_scope(
            session,
            actor,
            legacy_atom,
            project_id=view.project_id,
        )
        return view
    raise ForbiddenError("only the view's owner (or a co-owner) can do that")


# --- CRUD ---


def _validate_global_access(level: ShareLevel | None) -> str | None:
    """Server-wide OWNER would let anyone delete/transfer the view — grant
    co-ownership to specific people or teams instead (409)."""
    if level is ShareLevel.OWNER:
        raise ConflictError(
            ViewEntity.VIEW,
            reason="global_access cannot be 'owner' — grant co-ownership per person/team",
        )
    return level.value if level else None


async def create_view(session: AsyncSession, data: ViewCreate, actor: User) -> ViewRead:
    if data.project_id is not None:
        await projects_service.get_project(session, data.project_id)
    global_access = data.global_access
    # Server-wide visibility is a broadcast — the view.create atom gates it.
    # Sharing with specific people/teams is a personal act: item.read suffices.
    permission = Permission.VIEW_CREATE if global_access is not None else PERSONAL_VIEW_PERMISSION
    await _require_scope(session, actor, permission, project_id=data.project_id)
    view = View(
        project_id=data.project_id,
        name=data.name,
        view_type=data.view_type,  # validated (builtin or plugin key) in the schema
        query="",
        group_by=data.group_by,
        swimlane_by=data.swimlane_by,
        cycle_filter=_validate_cycle_filter(data.cycle_filter),
        # Ownership is never surrendered by sharing (spec 57) — the creator
        # owns the view in every visibility mode.
        owner_id=actor.id,
        global_access=_validate_global_access(global_access),
        position=data.position,
    )
    view.query = await _validate_query(session, view, actor, data.query)
    await _validate_axes(session, view)
    view.quick_filters = await _validate_quick_filters(session, view, actor, data.quick_filters)
    view.wip_limits = await _validate_wip_limits(session, view, data.wip_limits)
    view.columns = _validate_columns(data.columns)
    view.card_layout = _validate_card_layout(data.card_layout)
    view.column_order = _validate_bucket_order(data.column_order)
    view.swimlane_order = _validate_bucket_order(data.swimlane_order)
    view.collapse_empty_columns = data.collapse_empty_columns
    view.hidden_columns = _validate_bucket_order(data.hidden_columns)
    session.add(view)
    await session.flush()
    for entry in data.shares:
        await _add_share(session, view.id, entry, actor)
    await session.flush()
    await _emit(session, ViewEvent.CREATED, view, actor)
    return await _hydrate_one(session, actor, view)


async def _add_share(
    session: AsyncSession, view_id: uuid.UUID, entry: ViewShareEntry, actor: User
) -> None:
    """One view share = an access grant (spec 92). add_grant validates the subject
    exists + the level + dedupes."""
    if entry.user_id is not None:
        subject_type, subject_id = GrantSubject.USER, entry.user_id
    elif entry.team_id is not None:
        subject_type, subject_id = GrantSubject.TEAM, entry.team_id
    else:
        subject_type, subject_id = GrantSubject.GROUP, entry.group_id
    await access_service.add_grant(
        session,
        VIEW_RESOURCE,
        str(view_id),
        subject_type=subject_type,
        subject_id=subject_id,
        access=entry.level.value,
        actor_id=actor.id,
    )


async def list_views(
    session: AsyncSession,
    *,
    actor: User,
    project_id: uuid.UUID | None,
) -> list[ViewRead]:
    rows, _total = await page_views(session, actor=actor, project_id=project_id)
    return rows


async def page_views(session: AsyncSession, *, actor: User, include_shares: bool = True, **filters) -> tuple[list[ViewRead], int]:
    from . import directory
    rows, total = await directory.page(session, actor, **filters)
    return await _hydrate(session, actor, rows, include_shares=include_shares), total


async def get_view_read(session: AsyncSession, view_id: uuid.UUID, actor: User, *, include_shares: bool = True
) -> ViewRead:
    from . import directory
    stmt = await directory.query(session, actor)
    view = await session.scalar(stmt.where(View.id == view_id))
    if view is None:
        raise NotFoundError(ViewEntity.VIEW, view_id)
    return await _hydrate_one(session, actor, view, include_shares=include_shares)


async def update_view(
    session: AsyncSession, view_id: uuid.UUID, data: ViewUpdate, actor: User, *, include_shares: bool = True
) -> ViewRead:
    view = await _require_edit(session, view_id, actor)
    before = changes.snapshot(view, VIEW_FIELDS)
    if data.name is not None:
        view.name = data.name
    if data.view_type is not None:
        view.view_type = data.view_type
    if data.query is not None:
        view.query = await _validate_query(session, view, actor, data.query)
    # Axes: omitted = unchanged, explicit null = clear.
    axes_touched = False
    for axis_field in ("group_by", "swimlane_by"):
        if axis_field in data.model_fields_set:
            setattr(view, axis_field, getattr(data, axis_field))
            axes_touched = True
    if axes_touched:
        await _validate_axes(session, view)
    # Omitted = unchanged; explicit null/'' = all cycles.
    if "cycle_filter" in data.model_fields_set:
        view.cycle_filter = _validate_cycle_filter(data.cycle_filter)
    if data.quick_filters is not None:
        view.quick_filters = await _validate_quick_filters(
            session, view, actor, data.quick_filters
        )
    # Omitted = unchanged; explicit null/{} clears every limit (spec 76).
    if "wip_limits" in data.model_fields_set:
        view.wip_limits = await _validate_wip_limits(session, view, data.wip_limits)
    # Omitted = unchanged; explicit null/[] = back to the type's defaults (spec 108).
    if "columns" in data.model_fields_set:
        view.columns = _validate_columns(data.columns)
    # Omitted = unchanged; explicit null = back to the type's default card (spec 109).
    if "card_layout" in data.model_fields_set:
        view.card_layout = _validate_card_layout(data.card_layout)
    # RADD-855: omitted = unchanged; explicit null/[] = natural order.
    for order_field in ("column_order", "swimlane_order"):
        if order_field in data.model_fields_set:
            setattr(view, order_field, _validate_bucket_order(getattr(data, order_field)))
    # RADD-1175: column presence — same omitted/null idiom as the bucket order.
    if data.collapse_empty_columns is not None:
        view.collapse_empty_columns = data.collapse_empty_columns
    if "hidden_columns" in data.model_fields_set:
        view.hidden_columns = _validate_bucket_order(data.hidden_columns)
    if data.position is not None:
        view.position = data.position
    await session.flush()
    await _emit(
        session,
        ViewEvent.UPDATED,
        view,
        actor,
        diff=changes.diff_object(view, before, hidden=VIEW_HIDDEN, collections=VIEW_COLLECTIONS),
    )
    return await _hydrate_one(session, actor, view, include_shares=include_shares)


async def update_sharing(
    session: AsyncSession, view_id: uuid.UUID, data: ViewSharingUpdate, actor: User
) -> ViewRead:
    """Set the view's PUBLIC access level (spec 57 → spec 92): `global_access` = the
    ShareLevel every active user gets, or null = not public. Owner-gated (seeded
    owner-less: view.update); turning ON global visibility additionally needs
    view.create (it's a server-wide broadcast). Per-subject shares are managed
    grant-by-grant through the generic /grants API now."""
    view = await _require_manage(session, view_id, actor, legacy_atom=Permission.VIEW_UPDATE)
    return await _update_sharing(session, view, data, actor)


async def _update_sharing(
    session: AsyncSession, view: View, data: ViewSharingUpdate, actor: User, *, include_shares: bool = True
) -> ViewRead:
    # Invalid input rejects before permission checks (a plain member setting
    # global_access='owner' should hear "never valid", not "no broadcast rights").
    global_access = _validate_global_access(data.global_access)
    if data.global_access is not None and view.global_access is None:
        await _require_scope(
            session,
            actor,
            Permission.VIEW_CREATE,
            project_id=view.project_id,
        )
    previous = view.global_access
    view.global_access = global_access
    await session.flush()
    await _emit(
        session,
        ViewEvent.UPDATED,
        view,
        actor,
        diff=[e for e in [changes.change("global_access", previous, global_access)] if e],
    )
    return await _hydrate_one(session, actor, view, include_shares=include_shares)


async def transfer_ownership(
    session: AsyncSession, view_id: uuid.UUID, data: "ViewTransfer", actor: User
) -> ViewRead:
    """Reassign `owner_id` (spec 57): the owner or a co-owner (owner-level
    grantee) hands the view to another user, who must be able to use views in
    its scope (item.read there — 409 otherwise). The new owner's now-redundant
    grant rows are dropped; the PREVIOUS owner stays on as an editor so a
    transfer never locks anyone out by accident (the new owner can revoke)."""
    view = await _require_manage(session, view_id, actor, legacy_atom=Permission.VIEW_UPDATE)
    return await _transfer_ownership(session, view, data, actor)


async def _transfer_ownership(
    session: AsyncSession, view: View, data: ViewTransfer, actor: User, *, include_shares: bool = True
) -> ViewRead:
    target = await users_service.get_user(session, data.user_id)
    if not target.active:
        raise ConflictError(ViewEntity.VIEW, reason=f"user {target.email} is deactivated")
    if view.project_id is not None:
        project = await projects_service.get_project(session, view.project_id)
        target_perms = await authz.effective_permissions(session, target, project=project)
        can_use = authz.holds_base(target_perms, Permission.ITEM_READ)
    else:
        # All-projects view: the recipient needs item.read SOMEWHERE, not globally
        # (RADD-788) — otherwise handing a shared view to a colleague whose access
        # is project-scoped answered "they cannot use views in this scope" about a
        # person who uses views every day.
        can_use = bool(await authz.readable_projects(session, target))
    if not can_use:
        raise ConflictError(
            ViewEntity.VIEW, reason=f"{target.email} cannot use views in this scope"
        )
    previous_owner = view.owner_id
    if previous_owner == target.id:
        return await _hydrate_one(session, actor, view, include_shares=include_shares)
    previous_name = (
        (await users_service.users_by_ids(session, [previous_owner])).get(previous_owner)
        if previous_owner
        else None
    )
    view.owner_id = target.id
    # Drop the new owner's now-redundant share grant(s) (they own it outright).
    await _delete_user_shares(session, view.id, target.id)
    if previous_owner is not None:
        # The previous owner stays on as an editor so a transfer never locks anyone out.
        await _delete_user_shares(session, view.id, previous_owner)
        await access_service.add_grant(
            session,
            VIEW_RESOURCE,
            str(view.id),
            subject_type=GrantSubject.USER,
            subject_id=previous_owner,
            access=ShareLevel.EDITOR.value,
            actor_id=actor.id,
        )
    await session.flush()
    await _emit(
        session,
        ViewEvent.UPDATED,
        view,
        actor,
        diff=[
            {
                "field": "owner",
                "from": previous_name.name if previous_name else None,
                "to": target.name,
            }
        ],
    )
    return await _hydrate_one(session, actor, view, include_shares=include_shares)


async def _delete_user_shares(
    session: AsyncSession, view_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await access_service.remove_subject_grants(
        session,
        VIEW_RESOURCE,
        str(view_id),
        subject_type=GrantSubject.USER,
        subject_id=user_id,
    )


async def delete_view(session: AsyncSession, view_id: uuid.UUID, actor: User) -> None:
    view = await _require_manage(session, view_id, actor, legacy_atom=Permission.VIEW_DELETE)
    await _emit(session, ViewEvent.DELETED, view, actor)
    # Grants have no FK to the polymorphic view resource — clear them explicitly.
    await access_service.clear_resource(session, VIEW_RESOURCE, str(view.id))
    await session.delete(view)


#: What a view edit can touch (spec 123). Layout blobs record only that they
#: changed — a card layout's JSON is not something an auditor reads as a value.
VIEW_FIELDS: tuple[str, ...] = (
    "name", "view_type", "query", "group_by", "swimlane_by", "cycle_filter",
    "quick_filters", "wip_limits", "columns", "card_layout", "column_order",
    "swimlane_order", "collapse_empty_columns", "hidden_columns", "position",
)
VIEW_HIDDEN: tuple[str, ...] = ("quick_filters", "wip_limits", "columns", "card_layout")
VIEW_COLLECTIONS: tuple[str, ...] = ("column_order", "swimlane_order", "hidden_columns")


async def _emit(
    session: AsyncSession,
    event_type: ViewEvent,
    view: View,
    actor: User,
    *,
    share_count: int | None = None,
    diff: list[dict] | None = None,
) -> None:
    payload = {
        "name": view.name,
        "view_type": view.view_type,
        "project_id": str(view.project_id) if view.project_id else None,
        # Visible beyond the owner (server-wide or seeded owner-less);
        # per-grant shares ride along when the emitter changed them.
        "shared": view.owner_id is None or view.global_access is not None,
        "global_access": view.global_access,
    }
    if share_count is not None:
        payload["share_count"] = share_count
    await events.emit(
        session,
        event_type=event_type,
        entity_type=ViewEntity.VIEW,
        entity_id=view.id,
        actor_id=actor.id,
        payload=payload,
        subjects={"project": view.project_id},
        changes=diff,
    )


# --- card-layout preset library (spec 109) -----------------------------------
# Instance-wide named layouts, copy-on-apply: the client PATCHes the chosen
# preset's layout onto the view, so a later preset edit never restyles boards.


async def _emit_preset(
    session: AsyncSession,
    event_type: ViewEvent,
    preset: CardLayoutPreset,
    actor: User,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=ViewEntity.CARD_PRESET,
        entity_id=preset.id,
        actor_id=actor.id,
        payload={"name": preset.name},
        changes=diff,
    )


async def list_card_presets(session: AsyncSession) -> list[CardLayoutPreset]:
    result = await session.execute(
        select(CardLayoutPreset).order_by(CardLayoutPreset.position, CardLayoutPreset.name)
    )
    return list(result.scalars())


async def get_card_preset(session: AsyncSession, preset_id: uuid.UUID) -> CardLayoutPreset:
    preset = await session.get(CardLayoutPreset, preset_id)
    if preset is None:
        raise NotFoundError(ViewEntity.CARD_PRESET, preset_id)
    return preset


def _preset_layout(layout: CardLayout) -> dict[str, Any]:
    """A preset's layout passes the same validator as views.card_layout, but an
    empty layout (validator -> None) is meaningless as a library entry."""
    validated = _validate_card_layout(layout)
    if validated is None:
        raise ConflictError(ViewEntity.CARD_PRESET, reason="a preset needs at least one cell")
    return validated


async def create_card_preset(
    session: AsyncSession, data: CardPresetCreate, actor: User
) -> CardLayoutPreset:
    preset = CardLayoutPreset(
        name=data.name,
        layout=_preset_layout(data.layout),
        position=data.position,
    )
    session.add(preset)
    await session.flush()
    await _emit_preset(session, ViewEvent.CARD_PRESET_CREATED, preset, actor)
    return preset


async def update_card_preset(
    session: AsyncSession, preset_id: uuid.UUID, data: CardPresetUpdate, actor: User
) -> CardLayoutPreset:
    preset = await get_card_preset(session, preset_id)
    before = changes.snapshot(preset, ("name", "layout", "position"))
    if data.name is not None:
        preset.name = data.name
    if data.layout is not None:
        preset.layout = _preset_layout(data.layout)
    if data.position is not None:
        preset.position = data.position
    await session.flush()
    await _emit_preset(
        session,
        ViewEvent.CARD_PRESET_UPDATED,
        preset,
        actor,
        changes.diff_object(preset, before, hidden=("layout",)),
    )
    return preset


async def delete_card_preset(session: AsyncSession, preset_id: uuid.UUID, actor: User) -> None:
    preset = await get_card_preset(session, preset_id)
    await session.delete(preset)
    await session.flush()
    await _emit_preset(session, ViewEvent.CARD_PRESET_DELETED, preset, actor)


# --- curated membership (roadmap wave) ------------------------------------


async def add_member(
    session: AsyncSession, view_id: uuid.UUID, item_id: uuid.UUID, actor: User
) -> None:
    """Pin an item to the view (idempotent). Edit-gated like any definition
    write; the item must exist, but is NOT RBAC-checked here — reads flow
    through the item dialect (`roadmap = <view>`), where item RBAC applies."""
    view = await _require_edit(session, view_id, actor)
    await items_service.require_item(session, item_id)
    await session.execute(
        pg_insert(ViewMember)
        .values(view_id=view.id, item_id=item_id, added_by=actor.id)
        .on_conflict_do_nothing()
    )
    await session.flush()


async def remove_member(
    session: AsyncSession, view_id: uuid.UUID, item_id: uuid.UUID, actor: User
) -> None:
    """Unpin an item from the view (idempotent)."""
    view = await _require_edit(session, view_id, actor)
    await session.execute(
        delete(ViewMember).where(
            ViewMember.view_id == view.id, ViewMember.item_id == item_id
        )
    )
    await session.flush()


async def save_view(session, view_id, data, *, actor):
    """Public facade for an atomic definition/sharing/ownership save."""
    from .sharing import save

    return await save(session, view_id, data, actor=actor)
