"""Directory-group reconcile + group import (spec 84 → RADD-829).

GROUPS are the sync surface now, not linked teams: the directory's truth lives
in `groups` rows, whose membership is wholly sync-owned (no manual path, so no
MemberSource bookkeeping — the planner's job collapsed into a set replace).
Teams reach the directory by holding a group as a member; the sync never
touches team_members again.

Three consumers share the reconcile: the login-time per-user sync (direct
bind, no service account needed), the on-demand import, and the
`ldap.groupsync` PeriodicLoop (bind account + run_workers gated). Unknown
directory members are NEVER auto-provisioned by a reconcile — provisioning is
the explicit import path only.

The spec-87 two-path invariant moved here with the health flag: the periodic
loop refuses removals while a group's DN stops resolving (a renamed/deleted
group must not read as "everyone left"), and the login path holds removals for
flagged groups while still applying joins.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.groups import service as groups_service
from radd.modules.groups.models import Group
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.worker import PeriodicLoop

from . import groups as directory, service, state
from .types import DirectoryUnreachable, SyncKind

logger = logging.getLogger(__name__)

# Cap the error list persisted per run in directory_sync_state — the JSONB row
# is a status line, not a log (shared with the user-sync loop, spec 85).
MAX_RECORDED_ERRORS = 20


class StaleDirectoryGroup(Exception):
    """The group no longer resolves in AD (spec 87) — renamed, moved, or
    deleted. Raised instead of reconciling, so a vanished group cannot be read
    as "the group is now empty" and drain its memberships."""

    def __init__(self, group_dn: str):
        self.group_dn = group_dn
        super().__init__(f"directory group {group_dn} no longer exists — memberships kept")


# --- reconciling one group ----------------------------------------------------


async def reconcile_group(
    session: AsyncSession, group: Group
) -> tuple[int, int]:
    """Full reconcile of ONE group against the directory (service account):
    resolve the group's TRANSITIVE people in AD, replace the `group_members`
    rows, and mirror its DIRECT parent edges (RADD-831 — the structure the old
    sync resolved transitively and threw away). Returns (added, removed).

    Spec 87 stale-group guard: an empty transitive search is ambiguous — the
    group may genuinely be empty, or renamed/deleted (exactly the DNs that
    change in a domain reorg). Confirm the group still resolves before
    believing an empty answer; `get_group` raises DirectoryUnreachable on an
    outage so it propagates rather than flagging a healthy group.

    Edge semantics (the RADD-831 invariant): edges are written only from a
    SUCCESSFUL read of the child's own `memberOf` — an unreadable directory
    raises before any edge write, so a missing PARENT in a nested chain can
    never read as "the children have no parent". A parent that is not
    mirrored simply has no representable edge (mirroring is opt-in via the
    import); a parent deleted in AD drops out of the child's memberOf, which
    is the honest answer."""
    found = await directory.get_group(group.dn)
    if found is None:
        await groups_service.mark_missing(session, group, missing=True)
        raise StaleDirectoryGroup(group.dn)
    await groups_service.mark_missing(session, group, missing=False)
    members = await directory.search_group_members(session, group.dn)
    users_by_email = await auth_service.users_by_emails(
        session, [member.email for member in members]
    )
    added, removed = await groups_service.replace_members(
        session, group, [user.id for user in users_by_email.values()]
    )
    mirrored_parents = await groups_service.groups_by_dns(session, found.member_of)
    await groups_service.set_parents(
        session, group, [parent.id for parent in mirrored_parents.values()]
    )
    return added, removed


# --- login-time per-user sync (spec 84 §1a) -----------------------------------


async def sync_login_membership(
    session: AsyncSession, user: User, groups: list[Group], member_dns: frozenset[str]
) -> None:
    """The direct-bind connection already answered which mirrored groups the
    user is transitively in (`member_dns`); join/leave only THIS user's rows.
    Removals are held for flagged groups — "not a member" is what a
    non-existent DN always answers, and believing it would drain the group one
    login at a time.

    DECISION (RADD-831): the login path keeps the per-user PROBE
    (memberOf:IN_CHAIN against each mirrored DN on the user's own connection)
    rather than walking the mirrored edge graph. The probe asks AD the
    transitive question directly — always current, needs no service account —
    while an edge walk is only as fresh as the last periodic sync, and a login
    must not depend on it. The edges exist for provenance (the inspector's
    path) and the ancestors closure, not for authentication."""
    for group in groups:
        if group.dn in member_dns:
            await groups_service.replace_members(
                session,
                group,
                await _with_user(session, group, user.id, add=True),
            )
        elif group.directory_missing_since is None:
            await groups_service.replace_members(
                session,
                group,
                await _with_user(session, group, user.id, add=False),
            )


async def _with_user(
    session: AsyncSession, group: Group, user_id: uuid.UUID, *, add: bool
) -> set[uuid.UUID]:
    from sqlalchemy import select

    from radd.modules.groups.models import GroupMember

    current = set(
        (
            await session.execute(
                select(GroupMember.user_id).where(GroupMember.group_id == group.id)
            )
        ).scalars()
    )
    return current | {user_id} if add else current - {user_id}


# --- group import (spec 84 §2) ------------------------------------------------


@dataclass(frozen=True)
class GroupImportOutcome:
    group_dn: str
    cn: str
    team_id: uuid.UUID | None
    created: bool
    members_added: int
    users_provisioned: int
    error: str | None = None


async def import_groups(
    session: AsyncSession,
    group_dns: list[str],
    provision_members: bool,
    actor_id: uuid.UUID | None = None,
) -> list[GroupImportOutcome]:
    """Per DN: mirror the GROUP (find-or-create by dn), resolve its transitive
    people, optionally provision unknown users (spec-42 path: SSO-only account,
    source=ldap), replace its memberships — and keep the spec-84 UX by ensuring
    a TEAM of the same name holds the group, so an import still yields
    something attachable to projects."""
    outcomes: list[GroupImportOutcome] = []
    for group_dn in dict.fromkeys(group_dns):
        try:
            found = await directory.get_group(group_dn)
        except DirectoryUnreachable as exc:
            # Spec 87: distinct from "no such group" — reporting an outage as a
            # missing group would tell the admin their AD is wrong when it isn't.
            outcomes.append(
                GroupImportOutcome(
                    group_dn=group_dn,
                    cn="",
                    team_id=None,
                    created=False,
                    members_added=0,
                    users_provisioned=0,
                    error=str(exc),
                )
            )
            continue
        if found is None:
            outcomes.append(
                GroupImportOutcome(
                    group_dn=group_dn,
                    cn="",
                    team_id=None,
                    created=False,
                    members_added=0,
                    users_provisioned=0,
                    error="group not found in the directory",
                )
            )
            continue
        group = await groups_service.upsert_group(session, dn=found.dn, name=found.cn)
        # Mirror the nesting edges representable at this point (RADD-831):
        # parents already mirrored link up now; importing a parent LATER links
        # the other direction on its own reconcile.
        mirrored_parents = await groups_service.groups_by_dns(session, found.member_of)
        await groups_service.set_parents(
            session, group, [parent.id for parent in mirrored_parents.values()]
        )
        members = await directory.search_group_members(session, group.dn)
        provisioned = 0
        if provision_members:
            known = await auth_service.users_by_emails(session, [m.email for m in members])
            for member in members:
                if member.email in known:
                    continue
                _user, was_created = await service.find_or_create_user(session, member)
                if was_created:
                    provisioned += 1
        users_by_email = await auth_service.users_by_emails(
            session, [m.email for m in members]
        )
        added, _removed = await groups_service.replace_members(
            session, group, [u.id for u in users_by_email.values()]
        )
        team, created = await _team_holding_group(session, group, actor_id)
        outcomes.append(
            GroupImportOutcome(
                group_dn=group.dn,
                cn=found.cn,
                team_id=team.id,
                created=created,
                members_added=added,
                users_provisioned=provisioned,
            )
        )
    return outcomes


async def _team_holding_group(
    session: AsyncSession, group: Group, actor_id: uuid.UUID | None
):
    """Ensure a team of the group's name holds the group as a member — the
    RADD-829 shape of "import AD group as team". Idempotent."""
    existing = {team.name: team for team in await teams_service.list_teams(session)}
    team = existing.get(group.name)
    created = False
    if team is None:
        team = await teams_service.create_team(
            session, TeamCreate(name=group.name), actor_id=actor_id
        )
        created = True
    if group.id not in {g.id for g in await teams_service.team_groups(session, team.id)}:
        await teams_service.add_team_group(session, team.id, group.id, actor_id=actor_id)
    return team, created


# --- the periodic reconcile loop (spec 84 §1b) --------------------------------


#: RADD-848: the interval the loop's lambda reads — seeded from env, refreshed
#: from the settings cascade each tick, so a Directory-page edit applies from
#: the next cycle without a restart (the lambda itself has no session).
_interval: float = settings.ldap_group_sync_seconds


async def run_group_sync(session: AsyncSession) -> dict:
    """One full reconcile of every mirrored group, on the CALLER's session —
    shared by the periodic tick and POST /ldap/sync/groups (RADD-848).
    Per-group failures are logged, never fatal (the slas-engine idiom); the
    run is recorded in `directory_sync_state` (kind=group_sync) for
    GET /ldap/sync-status."""
    groups_seen = added_total = removed_total = 0
    errors: list[str] = []
    for group in await groups_service.list_groups(session):
        groups_seen += 1
        try:
            added, removed = await reconcile_group(session, group)
            added_total += added
            removed_total += removed
        except StaleDirectoryGroup as exc:
            # Expected operational state (a group renamed/deleted in AD), not a
            # bug: the group is flagged and left intact, so this is a warning
            # surfaced on the sync-status page rather than a traceback.
            logger.warning("ldap groupsync: %s", exc)
            errors.append(f"{group.name}: {exc}")
        except Exception as exc:
            logger.exception("ldap groupsync: reconciling group %s failed", group.id)
            errors.append(f"{group.name}: {exc}")
    payload = {
        "groups": groups_seen,
        "added": added_total,
        "removed": removed_total,
        "errors": errors[:MAX_RECORDED_ERRORS],
    }
    await state.record_run(session, SyncKind.GROUP_SYNC, payload)
    return payload


async def run_once() -> int:
    """One tick of the periodic loop."""
    global _interval
    async with SessionLocal() as session:
        # RADD-846: resolve the connection first; no bind account = dormant.
        await service.refresh_conn(session)
        from radd.modules.settings import service as settings_service
        from radd.modules.settings.types import SettingKey

        _interval = float(
            await settings_service.resolve(session, SettingKey.LDAP_GROUP_SYNC_SECONDS)
            or settings.ldap_group_sync_seconds
        )
        if not service.bind_account_enabled():
            return 0
        payload = await run_group_sync(session)
        await session.commit()
    return payload["added"] + payload["removed"]


_loop = PeriodicLoop(
    run_once,
    interval=lambda: _interval,  # RADD-848: cascade-refreshed each tick
    name="ldap-groupsync",
    # Web-only processes skip (spec 48 split). The bind check moved INSIDE
    # run_once (RADD-846) — see usersync for why a gate here would be wrong.
    enabled=lambda: settings.run_workers,
    sleep_first=True,  # nothing to burst at startup; the login path covers freshness
)

start = _loop.start
stop = _loop.stop
