"""Dashboard CRUD + ownership/sharing (spec 75).

The sharing semantics are the spec-57 view idiom VERBATIM (views/service.py):
visibility = owner ∪ user/team grantees ∪ every active user when global_access
is set; non-visible → 404 (admins included — privacy over acknowledgment);
editor grantees change the definition + widgets; the owner and OWNER-level
grantees (co-owners) manage sharing, delete, and transfer. The only spec-57
branch that does NOT exist here is the seeded owner-less fallback — every
dashboard has an owner from birth. Widget CRUD + config validation live in
widgets.py.
"""

import uuid

from sqlalchemy import select
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
from radd.modules.teams import service as teams_service
from radd.modules.groups import service as groups_service
from radd.modules.views.schemas import ShareGroupRef, ShareTeamRef, ShareUserRef

from .models import Dashboard, DashboardWidget
from .schemas import (
    DashboardCreate,
    DashboardRead,
    DashboardShareEntry,
    DashboardShareRead,
    DashboardSharingUpdate,
    DashboardTransfer,
    DashboardUpdate,
    WidgetRead,
)
from .types import DashboardEntity, DashboardEvent, ShareLevel, WidgetType

# Personal use (create private, edit own/granted) needs only the member floor —
# `authz.require_member`; the dashboard.* atoms gate the server-wide broadcast.
#
# That floor used to be spelled as a constant naming `item.read` at GLOBAL scope,
# which RADD-788 showed is not the same question: a person whose access is
# project-scoped is a member and holds nothing globally. The constant is gone
# rather than repointed, because its whole job was to name a scope that was wrong.


def _read_widget_type(value: str) -> WidgetType | str:
    """Builtin values read back as the WidgetType enum (byte-identical); a
    plugin-contributed widget_type (registries.widget_types) has no enum member,
    so it stays the raw string — WidgetType(value) would raise for it (spec 94)."""
    try:
        return WidgetType(value)
    except ValueError:
        return value


# Dashboard shares are grants in the generic access framework (spec 92, adopted
#): resource_type "dashboard", resource_id = the dashboard id, subject
# user/team, access = a ShareLevel (hierarchical viewer<editor<owner),
# owner-CLOSED by default, NOT project-scoped (dashboards are global). Until now
# this module carried its own `dashboard_shares` table — a verbatim copy of the
# `view_shares` semantics that spec 92 deleted on the views side.
# `global_access` + `owner_id` stay on the Dashboard row (a public level + the
# accountable owner — not per-subject grants).
DASHBOARD_RESOURCE = "dashboard"


# --- sharing resolution (spec 57, adapted) ---


async def _shares_by_dashboard(
    session: AsyncSession, dashboard_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[AccessGrant]]:
    """The dashboard-share grants grouped by dashboard id (batch, no N+1)."""
    if not dashboard_ids:
        return {}
    id_map = {str(d): d for d in dashboard_ids}
    grants = await access_service.grants_for_resources(
        session, DASHBOARD_RESOURCE, list(id_map)
    )
    return {id_map[rid]: rows for rid, rows in grants.items()}


def _grant_level(
    dashboard: Dashboard,
    shares: list[AccessGrant],
    actor_id: uuid.UUID,
    team_ids: set[uuid.UUID],
    group_ids: set[uuid.UUID],
) -> ShareLevel | None:
    """The highest ShareLevel the actor holds via direct/team/group grants or
    global_access — None = the dashboard is invisible to them. `group_ids` is
    the TRANSITIVE closure (RADD-832), so a share with a parent group reaches
    nested members."""
    level = access_service.shared_resource_level(
        DASHBOARD_RESOURCE, shares, user_id=actor_id, team_ids=team_ids,
        group_ids=group_ids, global_access=dashboard.global_access,
    )
    return ShareLevel(level) if level is not None else None


async def _widgets_by_dashboard(
    session: AsyncSession, dashboard_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[DashboardWidget]]:
    if not dashboard_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(DashboardWidget)
                .where(DashboardWidget.dashboard_id.in_(dashboard_ids))
                .order_by(DashboardWidget.position, DashboardWidget.created_at)
            )
        )
        .scalars()
        .all()
    )
    result: dict[uuid.UUID, list[DashboardWidget]] = {}
    for widget in rows:
        result.setdefault(widget.dashboard_id, []).append(widget)
    return result


async def _hydrate(
    session: AsyncSession, actor: User, dashboards: list[Dashboard], *, include_shares: bool = True
) -> list[DashboardRead]:
    """Batch-build reads: sharing state, widgets, per-ACTOR capabilities."""
    if not dashboards:
        return []
    shares_map = await _shares_by_dashboard(session, [d.id for d in dashboards]) if include_shares else {}
    states = await _sharing_state(session, actor, [row.id for row in dashboards]) if not include_shares else {}
    widgets_map = await _widgets_by_dashboard(session, [d.id for d in dashboards])
    user_ids = {d.owner_id for d in dashboards if d.owner_id is not None}
    team_ids: set[uuid.UUID] = set()
    group_ids: set[uuid.UUID] = set()
    for shares in shares_map.values():
        user_ids |= {g.subject_id for g in shares if g.subject_type == GrantSubject.USER}
        team_ids |= {g.subject_id for g in shares if g.subject_type == GrantSubject.TEAM}
        group_ids |= {g.subject_id for g in shares if g.subject_type == GrantSubject.GROUP}
    users = await users_service.users_by_ids(session, user_ids)
    teams = await teams_service.teams_by_ids(session, team_ids)
    groups = await groups_service.groups_by_ids(session, group_ids)
    actor_teams = await teams_service.user_team_ids(session, actor.id)
    actor_groups = await groups_service.user_group_ids(session, actor.id)

    reads: list[DashboardRead] = []
    for dashboard in dashboards:
        shares = shares_map.get(dashboard.id, [])
        # Preserve deny policies outside the legacy positive-share editor's
        # reconciliation; the generic grants API exposes the complete policy.
        allowed_shares = [g for g in shares if g.effect == GrantEffect.ALLOW]
        grant = (_grant_level(dashboard, shares, actor.id, actor_teams, actor_groups) if include_shares
                 else states[dashboard.id][0])
        can_manage = dashboard.owner_id == actor.id or grant is ShareLevel.OWNER
        owner = users.get(dashboard.owner_id) if dashboard.owner_id else None
        reads.append(
            DashboardRead(
                id=dashboard.id,
                name=dashboard.name,
                description=dashboard.description,
                owner_id=dashboard.owner_id,
                owner=ShareUserRef(id=owner.id, name=owner.name) if owner else None,
                global_access=ShareLevel(dashboard.global_access)
                if dashboard.global_access
                else None,
                shares=[
                    DashboardShareRead(
                        id=g.id,
                        level=ShareLevel(g.access),
                        user=(
                            ShareUserRef(id=u.id, name=u.name)
                            if g.subject_type == GrantSubject.USER
                            and (u := users.get(g.subject_id))
                            else None
                        ),
                        team=(
                            ShareTeamRef(id=t.id, name=t.name)
                            if g.subject_type == GrantSubject.TEAM
                            and (t := teams.get(g.subject_id))
                            else None
                        ),
                        group=(
                            ShareGroupRef(id=grp.id, name=grp.name)
                            if g.subject_type == GrantSubject.GROUP
                            and (grp := groups.get(g.subject_id))
                            else None
                        ),
                    )
                    for g in allowed_shares
                ],
                shared=dashboard.global_access is not None or (len(allowed_shares) > 0 if include_shares else states[dashboard.id][1]),
                can_edit=can_manage or grant in (ShareLevel.EDITOR, ShareLevel.OWNER),
                can_manage=can_manage,
                position=dashboard.position,
                widgets=[
                    WidgetRead(
                        id=w.id,
                        widget_type=_read_widget_type(w.widget_type),
                        title=w.title,
                        width=w.width,
                        position=w.position,
                        config=w.config or {},
                    )
                    for w in widgets_map.get(dashboard.id, [])
                ],
                created_at=dashboard.created_at,
                updated_at=dashboard.updated_at,
            )
        )
    return reads


async def hydrate_one(session: AsyncSession, actor: User, dashboard: Dashboard, *,
                         include_shares: bool = True) -> DashboardRead:
    return (await _hydrate(session, actor, [dashboard], include_shares=include_shares))[0]


async def _sharing_state(session, actor, ids):
    if not ids:
        return {}
    level, shared = await access_service.shared_resource_state_expressions(session, actor,
        DASHBOARD_RESOURCE, resource_id=Dashboard.id, global_access=Dashboard.global_access)
    rows = await session.execute(select(Dashboard.id, level, shared).where(Dashboard.id.in_(ids)))
    return {row_id: (ShareLevel(value) if value else None, bool(has_shares))
            for row_id, value, has_shares in rows}



# --- access ---


async def get_dashboard(session: AsyncSession, dashboard_id: uuid.UUID) -> Dashboard:
    dashboard = await session.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise NotFoundError(DashboardEntity.DASHBOARD, dashboard_id)
    return dashboard


async def _load_visible(
    session: AsyncSession, dashboard_id: uuid.UUID, actor: User
) -> tuple[Dashboard, ShareLevel | None]:
    """The dashboard + the actor's grant level; invisible → 404 (spec 57 —
    privacy over acknowledgment, admins included: not shared = not seen)."""
    dashboard = await get_dashboard(session, dashboard_id)
    grant = (await _sharing_state(session, actor, [dashboard.id]))[dashboard.id][0]
    if dashboard.owner_id != actor.id and grant is None:
        raise NotFoundError(DashboardEntity.DASHBOARD, dashboard_id)
    return dashboard, grant


async def require_edit(
    session: AsyncSession, dashboard_id: uuid.UUID, actor: User
) -> Dashboard:
    """Definition + widget writes: the owner or an editor/owner-level grantee.
    Visible-but-viewer → 403. Public within the module (widgets.py gates on it)."""
    await _lock_dashboard(session, str(dashboard_id))
    dashboard, grant = await _load_visible(session, dashboard_id, actor)
    if dashboard.owner_id == actor.id or grant in (ShareLevel.EDITOR, ShareLevel.OWNER):
        await authz.require_member(session, actor)  # RADD-788
        return dashboard
    raise ForbiddenError(
        "dashboard is shared with you as a viewer — ask the owner for edit access"
    )


async def _require_manage(
    session: AsyncSession, dashboard_id: uuid.UUID, actor: User
) -> Dashboard:
    """Sharing changes + delete + transfer: the owner or an OWNER-level grantee
    (co-owner) — editor grantees edit content, they don't re-share or delete."""
    await _lock_dashboard(session, str(dashboard_id))
    dashboard, grant = await _load_visible(session, dashboard_id, actor)
    await authz.require_member(session, actor)
    if dashboard.owner_id == actor.id or grant is ShareLevel.OWNER:
        return dashboard
    raise ForbiddenError("only the dashboard's owner (or a co-owner) can do that")


async def _can_manage_dashboard(
    session: AsyncSession, actor: User, resource_id: str, project_id: uuid.UUID | None
) -> bool:
    """Who may manage a dashboard's share grants: the owner or a co-owner
    (OWNER-level grant). Mirrors `_require_manage` for the generic /grants
    router. Dashboards are always owned, so there is no seeded owner-less
    fallback like views carry."""
    try:
        dashboard = await get_dashboard(session, uuid.UUID(resource_id))
    except (ValueError, NotFoundError):
        return False
    try:
        await authz.require_member(session, actor)
    except ForbiddenError:
        return False
    if dashboard.owner_id == actor.id:
        return True
    grant = (await _sharing_state(session, actor, [dashboard.id]))[dashboard.id][0]
    return grant is ShareLevel.OWNER


async def _lock_dashboard(session: AsyncSession, resource_id: str) -> None:
    try:
        resource_uuid = uuid.UUID(resource_id)
    except ValueError:
        raise NotFoundError(DashboardEntity.DASHBOARD, resource_id) from None
    row = await session.scalar(select(Dashboard).where(Dashboard.id == resource_uuid)
        .with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise NotFoundError(DashboardEntity.DASHBOARD, resource_id)


async def _dashboard_labels(session: AsyncSession, resource_ids) -> dict[str, str]:
    """Inspector labels (RADD-809): dashboard id -> name."""
    ids = []
    for raw in resource_ids:
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not ids:
        return {}
    rows = await session.execute(select(Dashboard.id, Dashboard.name).where(Dashboard.id.in_(ids)))
    return {str(dash_id): name for dash_id, name in rows.all()}


_DASHBOARD_SPEC = ResourceSpec(
    resource_type=DASHBOARD_RESOURCE,
    can_manage=_can_manage_dashboard,
    accesses=(ShareLevel.VIEWER.value, ShareLevel.EDITOR.value, ShareLevel.OWNER.value),
    default_open=False,  # private to its owner until shared
    hierarchical=True,  # viewer < editor < owner — effective level is the highest held
    subjects=(GrantSubject.USER, GrantSubject.TEAM, GrantSubject.GROUP),
    project_scoped=False,  # dashboards are global, not project-scoped
    label="Dashboard",
    label_for=_dashboard_labels,
    lock_resource=_lock_dashboard,
)
register_resource(_DASHBOARD_SPEC)


# --- CRUD ---


def _validate_global_access(level: ShareLevel | None) -> str | None:
    """Server-wide OWNER would let anyone delete/transfer the dashboard —
    grant co-ownership to specific people or teams instead (409)."""
    if level is ShareLevel.OWNER:
        raise ConflictError(
            DashboardEntity.DASHBOARD,
            reason="global_access cannot be 'owner' — grant co-ownership per person/team",
        )
    return level.value if level else None


async def _add_share(
    session: AsyncSession, dashboard_id: uuid.UUID, entry: DashboardShareEntry, actor: User
) -> None:
    """One dashboard share = an access grant (spec 92). `add_grant` validates the
    subject exists + the level + dedupes, which is exactly what the old
    `_validate_shares` hand-rolled here."""
    if entry.user_id is not None:
        subject_type, subject_id = GrantSubject.USER, entry.user_id
    elif entry.team_id is not None:
        subject_type, subject_id = GrantSubject.TEAM, entry.team_id
    else:
        subject_type, subject_id = GrantSubject.GROUP, entry.group_id
    await access_service.add_grant(
        session,
        DASHBOARD_RESOURCE,
        str(dashboard_id),
        subject_type=subject_type,
        subject_id=subject_id,
        access=entry.level.value,
        actor_id=actor.id,
    )


async def create_dashboard(
    session: AsyncSession, data: DashboardCreate, actor: User
) -> DashboardRead:
    # Invalid input rejects before permission checks (never-valid beats no-rights).
    global_access = _validate_global_access(data.global_access)
    # Server-wide visibility is a broadcast — the dashboard.create atom gates
    # it. Sharing with specific people/teams is a personal act: membership suffices.
    if global_access is not None:
        await authz.require(session, actor, Permission.DASHBOARD_CREATE)
    else:
        await authz.require_member(session, actor)  # RADD-788
    dashboard = Dashboard(
        name=data.name,
        description=data.description,
        # Ownership is never surrendered by sharing (spec 57) — the creator
        # owns the dashboard in every visibility mode.
        owner_id=actor.id,
        global_access=global_access,
        position=data.position,
    )
    session.add(dashboard)
    await session.flush()
    for entry in data.shares:
        await _add_share(session, dashboard.id, entry, actor)
    await session.flush()
    await emit(session, DashboardEvent.CREATED, dashboard, actor)
    return await hydrate_one(session, actor, dashboard)


async def list_dashboards(
    session: AsyncSession, *, actor: User
) -> list[DashboardRead]:
    rows, _total = await page_dashboards(session, actor=actor)
    return rows


async def page_dashboards(session: AsyncSession, *, actor: User, include_shares: bool = True, **filters) -> tuple[list[DashboardRead], int]:
    from . import directory
    rows, total = await directory.page(session, actor, **filters)
    return await _hydrate(session, actor, rows, include_shares=include_shares), total


async def get_dashboard_read(
    session: AsyncSession, dashboard_id: uuid.UUID, actor: User, *, include_shares: bool = True
) -> DashboardRead:
    dashboard, _ = await _load_visible(session, dashboard_id, actor)
    return await hydrate_one(session, actor, dashboard, include_shares=include_shares)


async def update_dashboard(
    session: AsyncSession, dashboard_id: uuid.UUID, data: DashboardUpdate, actor: User, *, include_shares: bool = True
) -> DashboardRead:
    dashboard = await require_edit(session, dashboard_id, actor)
    before = changes.snapshot(dashboard, ("name", "description", "position"))
    if data.name is not None:
        dashboard.name = data.name
    if data.description is not None:
        dashboard.description = data.description
    if data.position is not None:
        dashboard.position = data.position
    await session.flush()
    await emit(
        session, DashboardEvent.UPDATED, dashboard, actor,
        diff=changes.diff_object(dashboard, before),
    )
    return await hydrate_one(session, actor, dashboard, include_shares=include_shares)


async def update_sharing(
    session: AsyncSession, dashboard_id: uuid.UUID, data: DashboardSharingUpdate, actor: User
) -> DashboardRead:
    """Set the dashboard's PUBLIC access level (spec 57 → spec 92): `global_access`
    = the ShareLevel every active user gets, or null = not public. Owner/co-owner
    only; turning ON global visibility additionally needs dashboard.create (it is
    a server-wide broadcast). Per-subject shares are managed grant-by-grant
    through the generic /grants API now — this endpoint no longer accepts them."""
    dashboard = await _require_manage(session, dashboard_id, actor)
    return await _update_sharing(session, dashboard, data, actor)


async def _update_sharing(
    session: AsyncSession, dashboard: Dashboard, data: DashboardSharingUpdate, actor: User, *, include_shares: bool = True
) -> DashboardRead:
    global_access = _validate_global_access(data.global_access)
    if data.global_access is not None and dashboard.global_access is None:
        await authz.require(
            session, actor, Permission.DASHBOARD_CREATE
        )
    previous = dashboard.global_access
    dashboard.global_access = global_access
    await session.flush()
    share_count = await access_service.count_resource_grants(session, DASHBOARD_RESOURCE, str(dashboard.id))
    await emit(
        session, DashboardEvent.UPDATED, dashboard, actor, share_count=share_count,
        diff=[e for e in [changes.change("global_access", previous, global_access)] if e],
    )
    return await hydrate_one(session, actor, dashboard, include_shares=include_shares)


async def transfer_ownership(
    session: AsyncSession, dashboard_id: uuid.UUID, data: DashboardTransfer, actor: User
) -> DashboardRead:
    """Reassign `owner_id` (spec 57 idiom): owner or co-owner hands the
    dashboard to another active user (the global member floor — item.read —
    409 otherwise). The target's now-redundant grant rows are dropped; the
    PREVIOUS owner stays on as an editor grantee so a transfer never locks
    anyone out by accident (the new owner can revoke)."""
    dashboard = await _require_manage(session, dashboard_id, actor)
    return await _transfer_ownership(session, dashboard, data, actor)


async def _transfer_ownership(
    session: AsyncSession, dashboard: Dashboard, data: DashboardTransfer, actor: User, *, include_shares: bool = True
) -> DashboardRead:
    target = await users_service.get_user(session, data.user_id)
    if not target.active:
        raise ConflictError(
            DashboardEntity.DASHBOARD, reason=f"user {target.email} is deactivated"
        )
    target_perms = await authz.effective_permissions(
        session, target
    )
    if not authz.holds_base(target_perms, Permission.ITEM_READ):
        raise ConflictError(
            DashboardEntity.DASHBOARD,
            reason=f"{target.email} cannot use dashboards on this server",
        )
    previous_owner = dashboard.owner_id
    if previous_owner == target.id:
        return await hydrate_one(session, actor, dashboard, include_shares=include_shares)
    previous_user = (
        (await users_service.users_by_ids(session, [previous_owner])).get(previous_owner)
        if previous_owner
        else None
    )
    dashboard.owner_id = target.id
    # Drop the new owner's now-redundant grant(s) — they own it outright.
    await _delete_user_grants(session, dashboard.id, target.id)
    if previous_owner is not None:
        # The previous owner stays on as an editor so a transfer never locks
        # anyone out by accident (the new owner can revoke).
        await _delete_user_grants(session, dashboard.id, previous_owner)
        await access_service.add_grant(
            session,
            DASHBOARD_RESOURCE,
            str(dashboard.id),
            subject_type=GrantSubject.USER,
            subject_id=previous_owner,
            access=ShareLevel.EDITOR.value,
            actor_id=actor.id,
        )
    await session.flush()
    await emit(
        session, DashboardEvent.UPDATED, dashboard, actor,
        diff=[
            {
                "field": "owner",
                "from": previous_user.name if previous_user else None,
                "to": target.name,
            }
        ],
    )
    return await hydrate_one(session, actor, dashboard, include_shares=include_shares)


async def _delete_user_grants(
    session: AsyncSession, dashboard_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await access_service.remove_subject_grants(
        session,
        DASHBOARD_RESOURCE,
        str(dashboard_id),
        subject_type=GrantSubject.USER,
        subject_id=user_id,
    )


async def delete_dashboard(
    session: AsyncSession, dashboard_id: uuid.UUID, actor: User
) -> None:
    dashboard = await _require_manage(session, dashboard_id, actor)
    await emit(session, DashboardEvent.DELETED, dashboard, actor)
    await session.delete(dashboard)


async def emit(
    session: AsyncSession,
    event_type: DashboardEvent,
    dashboard: Dashboard,
    actor: User,
    *,
    share_count: int | None = None,
    diff: list[dict] | None = None,
) -> None:
    payload: dict[str, object] = {
        "name": dashboard.name,
        "shared": dashboard.global_access is not None,
        "global_access": dashboard.global_access,
    }
    if share_count is not None:
        payload["share_count"] = share_count
    await events.emit(
        session,
        event_type=event_type,
        entity_type=DashboardEntity.DASHBOARD,
        entity_id=dashboard.id,
        actor_id=actor.id,
        payload=payload,
        changes=diff,
    )


async def save_dashboard(session, dashboard_id, data, *, actor):
    """Public facade for an atomic definition/sharing/ownership save."""
    from .sharing import save

    return await save(session, dashboard_id, data, actor=actor)
