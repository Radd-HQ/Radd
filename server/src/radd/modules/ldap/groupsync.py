"""Directory-group reconcile + group import. `groups` rows are wholly sync-owned;
teams reach the directory by holding a group. Reconcile never auto-provisions
unknown members (only the explicit import does). A group whose DN stops
resolving is flagged and keeps its members — removals are held, never inferred."""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.groups import service as groups_service
from radd.modules.groups.service import Group
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate
from radd.worker import PeriodicLoop

from . import groups as directory, service, state
from .types import DirectoryUnreachable, SyncKind

logger = logging.getLogger(__name__)


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
    """Reconcile ONE group (service account): replace its members with AD's
    transitive set and mirror its DIRECT parent edges; returns (added, removed).
    An empty member search is ambiguous, so the group is re-read first: gone →
    flag + StaleDirectoryGroup, unreachable → DirectoryUnreachable propagates.
    Edges are written only from a successful read of the group's own `memberOf`."""
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
    """Join/leave only THIS user's rows, from the transitive probe the direct-bind
    connection already ran (always current, no service account — unlike the
    mirrored edges, which are only as fresh as the last sync). Removals are held
    for flagged groups: a missing DN answers "not a member" for everyone."""
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
    current = await groups_service.member_ids(session, group.id)
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

    @classmethod
    def failed(cls, group_dn: str, error: str) -> "GroupImportOutcome":
        return cls(group_dn=group_dn, cn="", team_id=None, created=False,
                   members_added=0, users_provisioned=0, error=error)


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
            # Distinct from "no such group": an outage must not read as a wrong AD.
            outcomes.append(GroupImportOutcome.failed(group_dn, str(exc)))
            continue
        if found is None:
            outcomes.append(GroupImportOutcome.failed(group_dn, "group not found in the directory"))
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
        "errors": errors[: settings.ldap_max_recorded_errors],
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
