"""User merge + hard delete.

Deliberate boundary exception: an identity's merge/delete repoints every
column that references the user by raw SQL rather than importing every module
(most modules import auth). KEEP THESE LISTS IN SYNC with new user FKs —
`tests/test_merge_coverage.py` and `test_user_delete.py` enforce it.
`service` imports this module, so `get_user*` are imported inside functions.
"""

import uuid

from sqlalchemy import select, text as sql
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.events import service as events

from .models import User
from .types import AuthEntity, AuthEvent, InstanceRole, UserSource

# What a delete would hand to the successor, in the words the dialog uses. Counted
# from the same columns the repoint moves, so the preview cannot drift from the act.
_CONTENT_COUNTS: tuple[tuple[str, str, str], ...] = (
    ("reported_items", "work_items", "reporter_id"),
    ("assigned_items", "work_items", "assignee_id"),
    ("comments", "comments", "author_id"),
    ("documents", "pages", "created_by"),
    ("views", "views", "owner_id"),
    ("dashboards", "dashboards", "owner_id"),
    ("owned_teams", "teams", "owner_id"),
    ("attachments", "attachments", "created_by"),
    ("approvals", "approval_requests", "requested_by"),
)

# Plain repoint: UPDATE … SET col = target WHERE col = source.
_MERGE_REPOINT: tuple[tuple[str, str], ...] = (
    ("work_items", "assignee_id"),
    ("work_items", "reporter_id"),
    # RADD-820: who made a grant is provenance; a merge asserts one person.
    ("access_grants", "granted_by"),
    ("global_role_grants", "granted_by"),
    ("comments", "author_id"),
    # Spec 116: an automation's author/default runner. Nulling would drop it back
    # to the system actor, quietly widening what it can do.
    ("automations", "created_by_id"),
    ("automation_runs", "actor_id"),  # RADD-1266: who a recorded run acted as
    ("automation_versions", "created_by_id"),  # RADD-1268: who saved a version
    ("comments", "resolved_by"),  # RADD-726: who closed an inline thread
    ("page_templates", "created_by"),  # RADD-712
    ("worklogs", "author_id"),
    # Leave follows the person on a merge; a hard delete destroys it first
    # (below), like worklogs — a successor must not show as on leave.
    ("leave_periods", "user_id"),
    ("leave_periods", "created_by"),
    ("notifications", "user_id"),
    ("notifications", "actor_id"),
    ("events", "actor_id"),
    ("item_web_links", "created_by"),
    ("item_vcs_links", "created_by"),
    # RADD-1258: unique per (provider, connection, username), never per user.
    ("vcs_user_links", "user_id"),
    ("attachments", "created_by"),
    ("pages", "created_by"),
    ("page_versions", "author_id"),
    ("item_page_links", "created_by"),
    ("views", "owner_id"),
    ("item_participants", "added_by"),
    ("view_members", "added_by"),  # roadmap wave: who pinned the item to the view
    ("dashboards", "owner_id"),
    # Spec 89: these three are FK NO ACTION — they block a hard delete.
    ("approval_requests", "requested_by"),
    ("approval_votes", "user_id"),
    ("pages", "updated_by"),
    # SET NULL on delete (which skips this row); a merge moves ownership with the person.
    ("teams", "owner_id"),
    # Operational history (importer runs/snapshots, backups, specs 99/100/117):
    # SET NULL would blank it, so it follows the survivor.
    ("jira_runs", "actor_id"),
    ("backup_runs", "actor_id"),
    ("backup_schedules", "created_by_id"),
    ("jira_snapshots", "actor_id"),
    ("confluence_snapshots", "actor_id"),
    ("confluence_runs", "actor_id"),
    # RADD-1044: the round-robin cursor follows the person (team_id is unique).
    ("team_assignment_cursors", "last_assigned_user_id"),
    # MERGE ONLY — federated logins follow the person (spec 110; unique on
    # (provider, subject), so no dedupe). `delete_user` destroys them first
    # (RADD-783): a successor must never inherit a credential.
    ("user_identities", "user_id"),
)
# (table, entity_cols, user_col): the entity columns make a row UNIQUE per user,
# so a source row the target already holds is dropped, not repointed onto a
# duplicate key. Null-safe (`IS NOT DISTINCT FROM`): a NULL scope column means
# global (spec 91), and `=` never matches NULL.
_MERGE_DEDUPE: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("item_watchers", ("item_id",), "user_id"),
    ("item_stars", ("item_id",), "user_id"),
    ("team_members", ("team_id",), "user_id"),
    # RADD-829: the next sync would converge these; a merge must not strand them meanwhile.
    ("group_members", ("group_id",), "user_id"),
    ("item_participants", ("item_id",), "user_id"),
    ("form_shares", ("form_id",), "user_id"),
    # Spec 87: CASCADE — without these two, deleting the merged source destroyed
    # the person's managed teams and role grants.
    ("team_managers", ("team_id",), "user_id"),
    # RADD-791: space_id is part of the key (a space is a scope).
    ("global_role_grants", ("role_id", "project_id", "space_id"), "user_id"),
)
# Credentials/preferences are identity-private — the target keeps its own.
_MERGE_PURGE: tuple[str, ...] = (
    "sessions", "api_tokens", "user_totp", "totp_recovery_codes", "notification_prefs",
    # RADD-1279: a pending enrolment hand-off is a credential like a session.
    "mfa_enrollment_tickets",
)

# RADD-784: access and personal state die with the account on a HARD DELETE,
# successor or not. A merge transfers them (one person); a delete must not —
# access exists because someone GRANTED it. Explicit rather than FK cascade.
_DELETE_WITH_ACCOUNT: tuple[tuple[str, str], ...] = (
    ("team_members", "user_id"),
    ("group_members", "user_id"),
    ("team_managers", "user_id"),
    ("global_role_grants", "user_id"),
    ("form_shares", "user_id"),
    ("item_participants", "user_id"),
    ("item_watchers", "user_id"),
    ("item_stars", "user_id"),
    ("notifications", "user_id"),
)


def _dedupe_sql(table: str, entity_cols: tuple[str, ...], user_col: str) -> str:
    """Drop the source's rows that the target ALREADY holds, so the repoint that
    follows cannot collide with a unique index. Null-safe on every entity column
    — see `_MERGE_DEDUPE`."""
    match = " AND ".join(f"o.{col} IS NOT DISTINCT FROM t.{col}" for col in entity_cols)
    return (
        f"DELETE FROM {table} t WHERE t.{user_col} = :src AND EXISTS ("
        f"SELECT 1 FROM {table} o WHERE {match} AND o.{user_col} = :dst)"
    )


async def _repoint_user_access_grants(
    session: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """Move a user's ACCESS GRANTS (spec 92 — view shares, user-subject field
    grants) to the target. `subject_id` is polymorphic (no FK), so it isn't caught
    by the FK-based repoint list; dedupe on the full grant identity first, then
    repoint the USER subject."""
    await session.execute(
        sql(
            "DELETE FROM access_grants t WHERE t.subject_type='user' AND t.subject_id=:src "
            "AND EXISTS (SELECT 1 FROM access_grants o WHERE o.subject_type='user' "
            "AND o.subject_id=:dst AND o.resource_type=t.resource_type "
            "AND o.resource_id=t.resource_id AND o.access=t.access "
            "AND o.project_id IS NOT DISTINCT FROM t.project_id)"
        ),
        {"src": source_id, "dst": target_id},
    )
    await session.execute(
        sql(
            "UPDATE access_grants SET subject_id=:dst "
            "WHERE subject_type='user' AND subject_id=:src"
        ),
        {"src": source_id, "dst": target_id},
    )


async def ensure_imported_user(
    session: AsyncSession,
    *,
    email: str,
    name: str,
    source: UserSource,
    actor_id: uuid.UUID | None = None,
) -> tuple[User, bool]:
    """Find-or-create a PASSWORD-LESS account for someone an importer named, so an
    importer never hand-builds a User nor credits an unknown author to whoever ran
    it. ACTIVE (the items service refuses an inactive assignee), password-less (a
    placeholder is not a way in); idempotent on email. Returns (user, created)."""
    from .service import get_user_by_email

    existing = await get_user_by_email(session, email)
    if existing is not None:
        return existing, False
    user = User(
        email=email.strip().lower(),
        name=name.strip() or email.split("@")[0],
        password_hash=None,
        source=source.value,
    )
    session.add(user)
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.USER_CREATED,
        entity_type=AuthEntity.USER,
        entity_id=user.id,
        actor_id=actor_id,
        payload={"email": user.email, "name": user.name, "source": user.source},
    )
    return user, True


async def merge_users(
    session: AsyncSession,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> User:
    """Fold `source` into `target`: every reference repoints to the target, then
    the source row is DELETED; the `user.deleted` event naming both accounts is
    the audit record."""
    from .service import get_user

    if source_id == target_id:
        raise ConflictError(AuthEntity.USER, reason="cannot merge a user into itself")
    source = await get_user(session, source_id)
    target = await get_user(session, target_id)
    for table, entity_cols, user_col in _MERGE_DEDUPE:
        await session.execute(sql(_dedupe_sql(table, entity_cols, user_col)),
                              {"src": source_id, "dst": target_id})
        await session.execute(
            sql(f"UPDATE {table} SET {user_col} = :dst WHERE {user_col} = :src"),
            {"src": source_id, "dst": target_id},
        )
    for table, column in _MERGE_REPOINT:
        await session.execute(
            sql(f"UPDATE {table} SET {column} = :dst WHERE {column} = :src"),
            {"src": source_id, "dst": target_id},
        )
    await _repoint_user_access_grants(session, source_id, target_id)
    for table in _MERGE_PURGE:
        await session.execute(
            sql(f"DELETE FROM {table} WHERE user_id = :src"), {"src": source_id}
        )
    # One person, so the survivor keeps their standing: folding an admin into a
    # member must not demote them (possibly the instance's only admin).
    if InstanceRole(source.instance_role) is InstanceRole.ADMIN:
        target.instance_role = InstanceRole.ADMIN.value
    await session.flush()

    # Deleted, not deactivated: everything moved to the target. Unlike
    # `delete_user`, worklogs moved too (one person, their hours). Emitted
    # before the delete so the trail keeps the email and name.
    await events.emit(
        session,
        event_type=AuthEvent.USER_DELETED,
        entity_type=AuthEntity.USER,
        entity_id=source.id,
        actor_id=actor_id,
        payload={
            "action": "merged",
            "email": source.email,
            "name": source.name,
            "into": str(target.id),
            "into_email": target.email,
        },
    )
    await session.delete(source)
    await session.flush()
    return target


async def user_content_summary(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """What this account owns (spec 89), for the delete dialog. `worklogs` is
    separate: a delete DISCARDS them rather than crediting a successor with hours
    they never worked."""
    summary: dict[str, int] = {}
    for label, table, column in _CONTENT_COUNTS:
        count = await session.scalar(
            sql(f"SELECT count(*) FROM {table} WHERE {column} = :u"), {"u": user_id}
        )
        summary[label] = int(count or 0)
    summary["worklogs"] = int(
        await session.scalar(
            sql("SELECT count(*) FROM worklogs WHERE author_id = :u"), {"u": user_id}
        )
        or 0
    )
    summary["worklog_seconds"] = int(
        await session.scalar(
            sql("SELECT COALESCE(sum(time_spent_seconds), 0) FROM worklogs WHERE author_id = :u"),
            {"u": user_id},
        )
        or 0
    )
    return summary


def ensure_deletable(user: User, actor: User, successor: User | None, owns: bool) -> None:
    """Pure guards for a hard delete (spec 89), unit-tested.

    Deleting yourself is refused for the same reason self-demotion is: the actor
    would vanish mid-request. A successor is required only when there is
    something to inherit, so emptying out placeholder accounts stays one click.
    """
    if user.id == actor.id:
        raise ConflictError(AuthEntity.USER, reason="you cannot delete your own account")
    if owns and successor is None:
        raise ConflictError(
            AuthEntity.USER,
            reason=f"{user.email} owns work — name someone to inherit it (reassign_to)",
        )
    if successor is not None:
        if successor.id == user.id:
            raise ConflictError(
                AuthEntity.USER, reason="the successor cannot be the account being deleted"
            )
        if not successor.active:
            raise ConflictError(
                AuthEntity.USER,
                reason=f"{successor.email} is deactivated and cannot inherit the work",
            )


def _permission_gaps(
    theirs: "frozenset[str]", ours: "frozenset[str]"
) -> list[str]:
    """Atoms in `theirs` that `ours` does not cover, lattice-aware (RADD-784):
    holding `item.read` covers a need for `item.read@own`, never the reverse."""
    from .types import base_permission, qualify_permission, relation_contains, relations_held

    missing: list[str] = []
    for base in sorted({base_permission(p) for p in theirs}):
        our_relations = relations_held(ours, base)
        for relation in sorted(relations_held(theirs, base)):
            if not any(relation_contains(held, relation) for held in our_relations):
                missing.append(qualify_permission(base, relation))
    return missing


async def successor_viability(
    session: AsyncSession, user: User, successor: User
) -> list[dict]:
    """Every scope where the successor holds LESS than the account being deleted
    (RADD-784) — empty means viable. Compared on EFFECTIVE permissions per
    scope (global, each project, each granted wiki space), so every delivery
    mechanism (roles, teams, groups, memberships) is covered without this
    function knowing any of them. A deletion never creates access; this check
    is what lets it refuse to assume any."""
    from radd.modules.projects.models import Project  # spine table (dev rule 1)

    from . import authz

    if InstanceRole(successor.instance_role) is InstanceRole.ADMIN:
        return []
    if InstanceRole(user.instance_role) is InstanceRole.ADMIN and user.active:
        return [
            {
                "scope_type": "instance",
                "label": "instance",
                "scope_id": None,
                "missing": ["instance administrator"],
            }
        ]

    gaps: list[dict] = []
    theirs = await authz.effective_permissions(session, user)
    ours = await authz.effective_permissions(session, successor)
    missing = _permission_gaps(frozenset(map(str, theirs)), frozenset(map(str, ours)))
    if missing:
        gaps.append(
            {"scope_type": "global", "label": "global", "scope_id": None, "missing": missing}
        )

    projects = list((await session.execute(select(Project))).scalars())
    their_by_project = await authz.permissions_for_projects(session, user, projects)
    our_by_project = await authz.permissions_for_projects(session, successor, projects)
    for project in sorted(projects, key=lambda p: p.key):
        missing = _permission_gaps(
            frozenset(map(str, their_by_project[project.id])),
            frozenset(map(str, our_by_project[project.id])),
        )
        if missing:
            gaps.append(
                {
                    "scope_type": "project",
                    "label": project.key,
                    "scope_id": project.id,
                    "missing": missing,
                }
            )

    space_ids = (
        await session.execute(
            sql("SELECT DISTINCT space_id FROM global_role_grants WHERE space_id IS NOT NULL")
        )
    ).scalars()
    for space_id in space_ids:
        theirs = await authz.effective_permissions(session, user, space_id=space_id)
        ours = await authz.effective_permissions(session, successor, space_id=space_id)
        missing = _permission_gaps(frozenset(map(str, theirs)), frozenset(map(str, ours)))
        if missing:
            gaps.append(
                {
                    "scope_type": "space",
                    "label": "wiki space",
                    "scope_id": space_id,
                    "missing": missing,
                }
            )
    return gaps


async def delete_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    successor_id: uuid.UUID | None = None,
    actor: User | None = None,
) -> dict[str, int]:
    """HARD-delete an account (spec 89), handing authored work to `successor_id`;
    returns what moved. Access and personal state die with the account
    (RADD-784); worklogs and leave are deleted, never reassigned."""
    from .service import get_user

    user = await get_user(session, user_id)
    successor = await get_user(session, successor_id) if successor_id else None
    summary = await user_content_summary(session, user_id)
    # owned_teams doesn't force a successor (RADD-784): team ownership goes
    # ownerless rather than transferring, so there is nothing to inherit.
    owns = any(
        summary[label]
        for label, _table, _column in _CONTENT_COUNTS
        if label != "owned_teams"
    ) or bool(summary["worklogs"])
    if actor is not None:
        ensure_deletable(user, actor, successor, owns)
    if successor is not None:
        # RADD-784: nothing transfers, so the successor must already HOLD what the
        # account holds; otherwise refuse, naming exactly what is missing.
        gaps = await successor_viability(session, user, successor)
        if gaps:
            detail = "; ".join(
                f"{gap['label']}: {', '.join(gap['missing'][:6])}"
                + (f" (+{len(gap['missing']) - 6} more)" if len(gap["missing"]) > 6 else "")
                for gap in gaps
            )
            raise ConflictError(
                AuthEntity.USER,
                reason=(
                    f"{successor.email} holds less access than {user.email} and cannot "
                    f"inherit their work — missing {detail}. Grant these first, or "
                    "choose another successor."
                ),
            )

    # Time records go first, so the repoint below cannot pick them up.
    await session.execute(sql("DELETE FROM worklogs WHERE author_id = :u"), {"u": user_id})
    # Leave follows the worklog rule: destroyed, never inherited — a successor
    # repointed onto someone's vacation would render as "on leave" everywhere.
    await session.execute(sql("DELETE FROM leave_periods WHERE user_id = :u"), {"u": user_id})
    # RADD-783: identities are DESTROYED, never inherited (they repoint only on a
    # merge): inheriting one let the deleted address sign in AS the successor.
    await session.execute(sql("DELETE FROM user_identities WHERE user_id = :u"), {"u": user_id})
    # RADD-784: ACCESS DIES WITH THE ACCOUNT, successor or not.
    for table, column in _DELETE_WITH_ACCOUNT:
        await session.execute(sql(f"DELETE FROM {table} WHERE {column} = :u"), {"u": user_id})
    # Their access grants too (a MERGE repoints them; a delete never hands them over).
    await session.execute(
        sql("DELETE FROM access_grants WHERE subject_type='user' AND subject_id = :u"),
        {"u": user_id},
    )
    if successor is not None:
        # Content + attribution only. Team OWNERSHIP is delegation, not content:
        # SET NULL leaves the team awaiting a deliberately chosen owner.
        for table, column in _MERGE_REPOINT:
            if (table, column) == ("teams", "owner_id"):
                continue
            await session.execute(
                sql(f"UPDATE {table} SET {column} = :dst WHERE {column} = :src"),
                {"src": user_id, "dst": successor.id},
            )
    else:
        # No successor: columns with NO foreign key (events.actor_id, …) would
        # dangle, so they are nulled; the user.deleted event keeps the email/name.
        await session.execute(
            sql("UPDATE events SET actor_id = NULL WHERE actor_id = :u"), {"u": user_id}
        )
        for table, column in (
            ("notifications", "actor_id"),
            ("attachments", "created_by"),
            ("item_web_links", "created_by"),
            ("item_vcs_links", "created_by"),
        ):
            await session.execute(
                sql(f"UPDATE {table} SET {column} = NULL WHERE {column} = :u"), {"u": user_id}
            )
    for table in _MERGE_PURGE:
        await session.execute(sql(f"DELETE FROM {table} WHERE user_id = :u"), {"u": user_id})

    # Emitted BEFORE the delete: events.actor_id has just been repointed, and the
    # row is about to stop existing, so this is the last chance to record it.
    await events.emit(
        session,
        event_type=AuthEvent.USER_DELETED,
        entity_type=AuthEntity.USER,
        entity_id=user.id,
        actor_id=actor.id if actor else None,
        payload={
            "email": user.email,
            "name": user.name,
            "reassigned_to": str(successor.id) if successor else None,
            "reassigned_to_email": successor.email if successor else None,
            "moved": {k: v for k, v in summary.items() if v},
        },
    )
    await session.flush()
    await session.delete(user)
    await session.flush()
    return summary
