"""Team↔AD-group reconcile + group import (spec 84).

The planner is PURE: directory membership (emails/UPNs) × current team_members
rows × the existing-user lookup → add/remove sets. It only ever removes
DIRECTORY-source rows and never adds a user who already has ANY row (a manual
row blocks a duplicate directory add), so applying it is idempotent.

Three consumers share it: the login-time per-user sync (direct bind, no service
account needed), the on-demand `POST /teams/{id}/directory-sync`, and the
`ldap.groupsync` PeriodicLoop (bind account + run_workers gated). Unknown
directory members are NEVER auto-provisioned by a reconcile — provisioning is
the explicit import path only."""

import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.teams import service as teams_service
from radd.modules.teams.models import Team
from radd.modules.teams.schemas import TeamCreate, TeamUpdate
from radd.modules.teams.types import MemberSource
from radd.worker import PeriodicLoop

from . import groups, service, state
from .types import DirectoryGroup, DirectoryUnreachable, DirectoryUser, SyncKind

logger = logging.getLogger(__name__)

# Cap the error list persisted per run in directory_sync_state — the JSONB row
# is a status line, not a log (shared with the user-sync loop, spec 85).
MAX_RECORDED_ERRORS = 20


class StaleDirectoryGroup(Exception):
    """The linked group no longer resolves in AD (spec 87) — renamed, moved, or
    deleted. Raised instead of reconciling, so a vanished group cannot be read as
    "the group is now empty" and empty the team."""

    def __init__(self, group_dn: str):
        self.group_dn = group_dn
        super().__init__(f"directory group {group_dn} no longer exists — team left untouched")


# --- the pure planner ---------------------------------------------------------


@dataclass(frozen=True)
class MemberRow:
    """The reconcile-relevant slice of one team_members row."""

    user_id: uuid.UUID
    source: str  # MemberSource value


@dataclass(frozen=True)
class ReconcilePlan:
    add_user_ids: frozenset[uuid.UUID]  # inserted as DIRECTORY-source rows
    remove_user_ids: frozenset[uuid.UUID]  # deleted ONLY where source=directory


def plan_reconcile(
    directory_emails: Iterable[str],
    current_rows: Iterable[MemberRow],
    users_by_email: Mapping[str, uuid.UUID],
) -> ReconcilePlan:
    """Directory truth → row deltas (pure).

    - joiner: resolved directory member with NO row of any source → add.
    - leaver: directory-source row whose user is no longer a directory member → remove.
    - manual rows are invisible to removal and block a duplicate directory add.
    - unknown directory members (no matching Radd user) are ignored here."""
    desired = {
        users_by_email[email.lower()]
        for email in directory_emails
        if email and email.lower() in users_by_email
    }
    rows = list(current_rows)
    present = {row.user_id for row in rows}
    directory_rows = {row.user_id for row in rows if row.source == MemberSource.DIRECTORY}
    return ReconcilePlan(
        add_user_ids=frozenset(desired - present),
        remove_user_ids=frozenset(directory_rows - desired),
    )


# --- applying a plan ----------------------------------------------------------


async def reconcile_team(
    session: AsyncSession,
    team: Team,
    directory_members: list[DirectoryUser] | None = None,
    actor_id: uuid.UUID | None = None,
) -> tuple[int, int]:
    """Full reconcile of ONE linked team against the directory (service
    account). `directory_members` may be pre-fetched (import path/tests);
    None = resolve transitively now. Returns (added, removed)."""
    if not team.directory_group_dn:
        return 0, 0
    if directory_members is None:
        # Spec 87 stale-group guard. An empty transitive search is ambiguous: the
        # group may genuinely have no members, or it may have been renamed/deleted
        # in AD — and those DNs are exactly the ones that change during a domain
        # reorg. Reconciling the second case would remove every directory member
        # and silently revoke whatever the team granted. Confirm the group still
        # resolves before believing an empty answer.
        #
        # `get_group` raises DirectoryUnreachable rather than answering None when
        # the directory can't be asked, so an outage propagates (the run records
        # an error and touches nothing) instead of flagging a healthy team as
        # stale. Only a definitive "not there" marks it.
        directory_members = await groups.search_group_members(session, team.directory_group_dn)
        if not directory_members and await groups.get_group(team.directory_group_dn) is None:
            await teams_service.mark_directory_health(session, team, missing=True)
            raise StaleDirectoryGroup(team.directory_group_dn)
        await teams_service.mark_directory_health(session, team, missing=False)
    emails = [member.email for member in directory_members]
    users_by_email = {
        email: user.id for email, user in (await auth_service.users_by_emails(session, emails)).items()
    }
    rows = [
        MemberRow(user_id=row.user_id, source=row.source)
        for row in await teams_service.team_member_rows(session, team.id)
    ]
    plan = plan_reconcile(emails, rows, users_by_email)
    return await teams_service.apply_directory_membership(
        session, team, plan.add_user_ids, plan.remove_user_ids, actor_id=actor_id
    )


async def sync_login_membership(
    session: AsyncSession, user: User, linked: list[Team], member_dns: frozenset[str]
) -> None:
    """Login-time per-user sync (spec 84 §1a): the direct-bind connection
    already answered which linked-team groups the user is transitively in
    (`member_dns`); join/leave only THIS user's directory-source rows."""
    for team in linked:
        if not team.directory_group_dn:
            continue
        rows = {
            row.user_id: row for row in await teams_service.team_member_rows(session, team.id)
        }
        row = rows.get(user.id)
        if team.directory_group_dn in member_dns:
            if row is None:
                await teams_service.apply_directory_membership(
                    session, team, [user.id], [], actor_id=user.id
                )
        elif row is not None and row.source == MemberSource.DIRECTORY:
            # Spec 87: while the group is known-missing, "not a member" is what a
            # non-existent DN always answers — believing it would drain the team
            # one login at a time. Joins still apply; only removals are held.
            if team.directory_missing_since is not None:
                continue
            await teams_service.apply_directory_membership(
                session, team, [], [user.id], actor_id=user.id
            )


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
    """Per group: create-or-link a team (name = CN), resolve TRANSITIVE members,
    optionally provision unknown users (spec-42 path: SSO-only account,
    source=ldap — a new active user holds the global member floor), then add
    directory-source memberships via the reconcile planner."""
    outcomes: list[GroupImportOutcome] = []
    for group_dn in dict.fromkeys(group_dns):
        try:
            group = await groups.get_group(group_dn)
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
        if group is None:
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
        team, created = await _team_for_group(session, group, actor_id)
        members = await groups.search_group_members(session, group.dn)
        provisioned = 0
        if provision_members:
            known = await auth_service.users_by_emails(session, [m.email for m in members])
            for member in members:
                if member.email in known:
                    continue
                _user, was_created = await service.find_or_create_user(session, member)
                if was_created:
                    provisioned += 1
        added, _removed = await reconcile_team(
            session, team, directory_members=members, actor_id=actor_id
        )
        outcomes.append(
            GroupImportOutcome(
                group_dn=group.dn,
                cn=group.cn,
                team_id=team.id,
                created=created,
                members_added=added,
                users_provisioned=provisioned,
            )
        )
    return outcomes


async def _team_for_group(
    session: AsyncSession, group: DirectoryGroup, actor_id: uuid.UUID | None
) -> tuple[Team, bool]:
    """Find the team already linked to this DN, else link the same-named team,
    else create one (linked)."""
    for team in await teams_service.linked_teams(session):
        if team.directory_group_dn == group.dn:
            return team, False
    existing = {
        team.name: team for team in await teams_service.list_teams(session)
    }
    if group.cn in existing:
        team = await teams_service.update_team(
            session,
            existing[group.cn].id,
            TeamUpdate(directory_group_dn=group.dn, directory_group_name=group.cn),
            actor_id=actor_id,
        )
        return team, False
    team = await teams_service.create_team(
        session, TeamCreate(name=group.cn), actor_id=actor_id
    )
    return (
        await teams_service.update_team(
            session,
            team.id,
            TeamUpdate(directory_group_dn=group.dn, directory_group_name=group.cn),
            actor_id=actor_id,
        ),
        True,
    )


# --- the periodic reconcile loop (spec 84 §1b) --------------------------------


async def run_once() -> int:
    """One tick: full reconcile of every linked team. Per-team failures are
    logged, never fatal (the slas-engine idiom). Spec 85: the run is recorded
    in `directory_sync_state` (kind=group_sync) for GET /ldap/sync-status."""
    teams_seen = added_total = removed_total = 0
    errors: list[str] = []
    async with SessionLocal() as session:
        for team in await teams_service.linked_teams(session):
            teams_seen += 1
            try:
                added, removed = await reconcile_team(session, team)
                added_total += added
                removed_total += removed
            except StaleDirectoryGroup as exc:
                # Expected operational state (a group renamed/deleted in AD), not a
                # bug: the team is flagged and left intact, so this is a warning
                # surfaced on the sync-status page rather than a traceback.
                logger.warning("ldap groupsync: %s", exc)
                errors.append(f"{team.name}: {exc}")
            except Exception as exc:
                logger.exception("ldap groupsync: reconciling team %s failed", team.id)
                errors.append(f"{team.name}: {exc}")
        await state.record_run(
            session,
            SyncKind.GROUP_SYNC,
            {
                "teams": teams_seen,
                "added": added_total,
                "removed": removed_total,
                "errors": errors[:MAX_RECORDED_ERRORS],
            },
        )
        await session.commit()
    return added_total + removed_total


_loop = PeriodicLoop(
    run_once,
    interval=lambda: settings.ldap_group_sync_seconds,
    name="ldap-groupsync",
    # Web-only processes skip (spec 48 split); no bind account = dormant.
    enabled=lambda: settings.run_workers and service.bind_account_enabled(),
    sleep_first=True,  # nothing to burst at startup; the login path covers freshness
)

start = _loop.start
stop = _loop.stop
