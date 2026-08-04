"""Dashboard CRUD + ownership/sharing (spec 75).

The sharing semantics are the spec-57 view idiom VERBATIM (views/service.py):
visibility = owner ∪ user/team grantees ∪ every active user when global_access
is set; non-visible → 404 (admins included — privacy over acknowledgment);
editor grantees change the definition + widgets; the owner and OWNER-level
grantees (co-owners) manage sharing, delete, and transfer. The only spec-57
branch that does NOT exist here is the legacy owner-less fallback — every
dashboard has an owner from birth. Widget CRUD + config validation live in
widgets.py.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.access import service as access_service
from radd.modules.access.models import AccessGrant
from radd.modules.access.registry import ResourceSpec, register_resource
from radd.modules.access.types import GrantSubject
from radd.modules.auth import authz, service as users_service
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.teams import service as teams_service
from radd.modules.views.schemas import ShareTeamRef, ShareUserRef

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
    rows = (
        (
            await session.execute(
                select(AccessGrant).where(
                    AccessGrant.resource_type == DASHBOARD_RESOURCE,
                    AccessGrant.resource_id.in_(list(id_map)),
                )
            )
        )
        .scalars()
        .all()
    )
    result: dict[uuid.UUID, list[AccessGrant]] = {}
    for grant in rows:
        result.setdefault(id_map[grant.resource_id], []).append(grant)
    return result


def _grant_level(
    dashboard: Dashboard,
    shares: list[AccessGrant],
    actor_id: uuid.UUID,
    team_ids: set[uuid.UUID],
) -> ShareLevel | None:
    """The highest ShareLevel the actor holds via direct grants, team grants,
    or global_access — None = the dashboard is invisible to them."""
    levels: set[ShareLevel] = {
        ShareLevel(grant.access)
        for grant in shares
        if (grant.subject_type == GrantSubject.USER and grant.subject_id == actor_id)
        or (grant.subject_type == GrantSubject.TEAM and grant.subject_id in team_ids)
    }
    if dashboard.global_access is not None:
        levels.add(ShareLevel(dashboard.global_access))
    for level in (ShareLevel.OWNER, ShareLevel.EDITOR, ShareLevel.VIEWER):
        if level in levels:
            return level
    return None


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
    session: AsyncSession, actor: User, dashboards: list[Dashboard]
) -> list[DashboardRead]:
    """Batch-build reads: sharing state, widgets, per-ACTOR capabilities."""
    if not dashboards:
        return []
    shares_map = await _shares_by_dashboard(session, [d.id for d in dashboards])
    widgets_map = await _widgets_by_dashboard(session, [d.id for d in dashboards])
    user_ids = {d.owner_id for d in dashboards if d.owner_id is not None}
    team_ids: set[uuid.UUID] = set()
    for shares in shares_map.values():
        user_ids |= {g.subject_id for g in shares if g.subject_type == GrantSubject.USER}
        team_ids |= {g.subject_id for g in shares if g.subject_type == GrantSubject.TEAM}
    users = await users_service.users_by_ids(session, user_ids)
    teams = await teams_service.teams_by_ids(session, team_ids)
    actor_teams = await teams_service.user_team_ids(session, actor.id)

    reads: list[DashboardRead] = []
    for dashboard in dashboards:
        shares = shares_map.get(dashboard.id, [])
        grant = _grant_level(dashboard, shares, actor.id, actor_teams)
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
                    )
                    for g in shares
                ],
                shared=dashboard.global_access is not None or len(shares) > 0,
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


async def hydrate_one(
    session: AsyncSession, actor: User, dashboard: Dashboard
) -> DashboardRead:
    return (await _hydrate(session, actor, [dashboard]))[0]


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
    shares = (await _shares_by_dashboard(session, [dashboard.id])).get(dashboard.id, [])
    team_ids = await teams_service.user_team_ids(session, actor.id)
    grant = _grant_level(dashboard, shares, actor.id, team_ids)
    if dashboard.owner_id != actor.id and grant is None:
        raise NotFoundError(DashboardEntity.DASHBOARD, dashboard_id)
    return dashboard, grant


async def require_edit(
    session: AsyncSession, dashboard_id: uuid.UUID, actor: User
) -> Dashboard:
    """Definition + widget writes: the owner or an editor/owner-level grantee.
    Visible-but-viewer → 403. Public within the module (widgets.py gates on it)."""
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
    dashboard, grant = await _load_visible(session, dashboard_id, actor)
    if dashboard.owner_id == actor.id or grant is ShareLevel.OWNER:
        return dashboard
    raise ForbiddenError("only the dashboard's owner (or a co-owner) can do that")


async def _can_manage_dashboard(
    session: AsyncSession, actor: User, resource_id: str, project_id: uuid.UUID | None
) -> bool:
    """Who may manage a dashboard's share grants: the owner or a co-owner
    (OWNER-level grant). Mirrors `_require_manage` for the generic /grants
    router. Dashboards are always owned, so there is no legacy owner-less
    fallback like views carry."""
    try:
        dashboard = await get_dashboard(session, uuid.UUID(resource_id))
    except (ValueError, NotFoundError):
        return False
    if dashboard.owner_id == actor.id:
        return True
    grants = (await _shares_by_dashboard(session, [dashboard.id])).get(dashboard.id, [])
    team_ids = await teams_service.user_team_ids(session, actor.id)
    return _grant_level(dashboard, grants, actor.id, team_ids) is ShareLevel.OWNER


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
    subjects=(GrantSubject.USER, GrantSubject.TEAM),
    project_scoped=False,  # dashboards are global, not project-scoped
    label="Dashboard",
    label_for=_dashboard_labels,
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
    subject_type = GrantSubject.USER if entry.user_id is not None else GrantSubject.TEAM
    await access_service.add_grant(
        session,
        DASHBOARD_RESOURCE,
        str(dashboard_id),
        subject_type=subject_type,
        subject_id=entry.user_id if entry.user_id is not None else entry.team_id,
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
    # Member floor (RADD-788): item.read in SOME project, not the global atom.
    if not await authz.readable_projects(session, actor):
        return []
    candidates = list(
        (
            await session.execute(
                select(Dashboard).order_by(Dashboard.position, Dashboard.name)
            )
        ).scalars()
    )
    shares_map = await _shares_by_dashboard(session, [d.id for d in candidates])
    team_ids = await teams_service.user_team_ids(session, actor.id)
    visible = [
        dashboard
        for dashboard in candidates
        if dashboard.owner_id == actor.id
        or _grant_level(dashboard, shares_map.get(dashboard.id, []), actor.id, team_ids)
        is not None
    ]
    return await _hydrate(session, actor, visible)


async def get_dashboard_read(
    session: AsyncSession, dashboard_id: uuid.UUID, actor: User
) -> DashboardRead:
    dashboard, _ = await _load_visible(session, dashboard_id, actor)
    return await hydrate_one(session, actor, dashboard)


async def update_dashboard(
    session: AsyncSession, dashboard_id: uuid.UUID, data: DashboardUpdate, actor: User
) -> DashboardRead:
    dashboard = await require_edit(session, dashboard_id, actor)
    if data.name is not None:
        dashboard.name = data.name
    if data.description is not None:
        dashboard.description = data.description
    if data.position is not None:
        dashboard.position = data.position
    await session.flush()
    await emit(session, DashboardEvent.UPDATED, dashboard, actor)
    return await hydrate_one(session, actor, dashboard)


async def update_sharing(
    session: AsyncSession, dashboard_id: uuid.UUID, data: DashboardSharingUpdate, actor: User
) -> DashboardRead:
    """Set the dashboard's PUBLIC access level (spec 57 → spec 92): `global_access`
    = the ShareLevel every active user gets, or null = not public. Owner/co-owner
    only; turning ON global visibility additionally needs dashboard.create (it is
    a server-wide broadcast). Per-subject shares are managed grant-by-grant
    through the generic /grants API now — this endpoint no longer accepts them."""
    dashboard = await _require_manage(session, dashboard_id, actor)
    global_access = _validate_global_access(data.global_access)
    if data.global_access is not None and dashboard.global_access is None:
        await authz.require(
            session, actor, Permission.DASHBOARD_CREATE
        )
    dashboard.global_access = global_access
    await session.flush()
    share_count = len((await _shares_by_dashboard(session, [dashboard.id])).get(dashboard.id, []))
    await emit(session, DashboardEvent.UPDATED, dashboard, actor, share_count=share_count)
    return await hydrate_one(session, actor, dashboard)


async def transfer_ownership(
    session: AsyncSession, dashboard_id: uuid.UUID, data: DashboardTransfer, actor: User
) -> DashboardRead:
    """Reassign `owner_id` (spec 57 idiom): owner or co-owner hands the
    dashboard to another active user (the global member floor — item.read —
    409 otherwise). The target's now-redundant grant rows are dropped; the
    PREVIOUS owner stays on as an editor grantee so a transfer never locks
    anyone out by accident (the new owner can revoke)."""
    dashboard = await _require_manage(session, dashboard_id, actor)
    target = await users_service.get_user(session, data.user_id)
    if not target.active:
        raise ConflictError(
            DashboardEntity.DASHBOARD, reason=f"user {target.email} is deactivated"
        )
    target_perms = await authz.effective_permissions(
        session, target
    )
    if Permission.ITEM_READ not in target_perms:
        raise ConflictError(
            DashboardEntity.DASHBOARD,
            reason=f"{target.email} cannot use dashboards on this server",
        )
    previous_owner = dashboard.owner_id
    if previous_owner == target.id:
        return await hydrate_one(session, actor, dashboard)
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
    await emit(session, DashboardEvent.UPDATED, dashboard, actor)
    return await hydrate_one(session, actor, dashboard)


async def _delete_user_grants(
    session: AsyncSession, dashboard_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await session.execute(
        delete(AccessGrant).where(
            AccessGrant.resource_type == DASHBOARD_RESOURCE,
            AccessGrant.resource_id == str(dashboard_id),
            AccessGrant.subject_type == GrantSubject.USER,
            AccessGrant.subject_id == user_id,
        )
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
    )
