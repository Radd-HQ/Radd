"""User merge + hard-delete, split out of `service.py` (RADD-902) along its own
"user merge (duplicate identities: seed + AD import + Jira import)" marker
(formerly lines 521-1115) — by far that file's biggest section, and the
raw-SQL repoint block is self-contained enough to be its own module.

Deliberate module-boundary exception (kept from the original file): merging or
deleting an identity is a cross-cutting maintenance operation on the user id
itself, so auth (the owner of users) repoints every referencing column by raw
SQL rather than importing every other module (which would invert the
dependency graph — most modules import auth). KEEP THESE LISTS IN SYNC when a
new table references a user id.

`get_user`/`get_user_by_email` are users CRUD and stay in `service.py`; they're
imported here (deferred, inside the functions that need them) rather than at
module level because `service.py` imports THIS module to re-export
`merge_users`/`delete_user`/etc under its own name — a top-level import here
would circle straight back into a module still being initialized.
"""

import uuid

from sqlalchemy import select
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
    # RADD-820: who made a grant is provenance, and a merge asserts one person
    # — the surviving identity IS the granter, same as authorship.
    ("access_grants", "granted_by"),
    ("global_role_grants", "granted_by"),
    ("comments", "author_id"),
    # Spec 116: an automation's author, and the identity its actions run as by
    # default. Repointed rather than nulled — a merge asserts one person, so the
    # surviving identity keeps authoring (and running) it. Nulling would silently
    # drop the automation back to the system actor, quietly widening what it can
    # do.
    ("automations", "created_by_id"),
    # RADD-726: who closed an inline thread. Plain attribution — a merge should
    # show the surviving identity as having resolved it, same as authorship.
    ("comments", "resolved_by"),
    # RADD-712: who wrote a page template. Attribution, like authorship.
    ("page_templates", "created_by"),
    ("worklogs", "author_id"),
    # A MERGE asserts one person, so their leave follows them. Hard DELETE
    # destroys leave first (below), same rule as worklogs — a successor must
    # not show as on vacation they never took.
    ("leave_periods", "user_id"),
    ("leave_periods", "created_by"),
    ("notifications", "user_id"),
    ("notifications", "actor_id"),
    ("events", "actor_id"),
    ("item_web_links", "created_by"),
    ("item_vcs_links", "created_by"),
    ("attachments", "created_by"),
    ("pages", "created_by"),
    ("page_versions", "author_id"),
    ("item_page_links", "created_by"),
    ("views", "owner_id"),
    ("item_participants", "added_by"),
    ("view_members", "added_by"),  # roadmap wave: who pinned the item to the view
    ("dashboards", "owner_id"),
    # Spec 89: these three block a hard delete (FK NO ACTION) and were ALSO
    # missing from the merge — a merged-away account kept holding its approvals
    # and doc edits. Found by diffing this list against every FK to users.id.
    ("approval_requests", "requested_by"),
    ("approval_votes", "user_id"),
    ("pages", "updated_by"),
    # Teams the person owns follow them; the column is ON DELETE SET NULL, so
    # without this a delete would silently leave those teams ownerless.
    ("teams", "owner_id"),
    # Spec 100: who ran an import / dry run / rollback. The successor inherits it
    # (operational history), rather than the run becoming anonymous.
    ("jira_runs", "actor_id"),
    # Spec 99: who took a backup / owns a schedule. SET NULL, so a delete would
    # quietly blank the operational history rather than hand it to the survivor.
    ("backup_runs", "actor_id"),
    ("backup_schedules", "created_by_id"),
    # Spec 100: who downloaded a Jira snapshot. SET NULL, same reasoning — the
    # successor inherits the cached download rather than it becoming anonymous.
    ("jira_snapshots", "actor_id"),
    # Spec 117: the same two facts for the Confluence importer — who downloaded a
    # snapshot, and who ran an import. Operational history, so it follows the
    # person rather than blanking.
    ("confluence_snapshots", "actor_id"),
    ("confluence_runs", "actor_id"),
    # Spec 110: federated logins follow the person. Merging the AD account into
    # the Google one (or back) must not cost either account its ability to sign
    # in — CASCADE would have destroyed the source's identities outright. Not in
    # _MERGE_DEDUPE: uniqueness is (provider_id, subject), so a survivor holding
    # two identities from one provider is legal and correct — it just means the
    # person had two accounts there, and now both open the same Radd user.
    #
    # MERGE ONLY (RADD-783). `delete_user` shares this list and must NOT repoint
    # identities: a merge says "these two are one person", a delete says "this
    # person is gone, give their work to someone else" — and handing over the
    # credential with the work let the deleted address sign in AS the successor.
    # `delete_user` destroys them before the loop runs.
    ("user_identities", "user_id"),
)
# (entity_col, user_col) unique pairs: drop source rows the target already has,
# then repoint the rest.
# (entity_cols, user_col): the entity columns are what makes a row UNIQUE per
# user, so a source row the target already holds is a COLLISION — dropped rather
# than repointed onto a duplicate key. Comparison is null-safe
# (`IS NOT DISTINCT FROM`), because a scope column can legitimately be NULL:
# `global_role_grants.project_id IS NULL` means the grant is global (spec 91),
# and `=` never matches NULL, so a plain equality check would let two "same"
# global grants through and violate the unique index.
_MERGE_DEDUPE: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("item_watchers", ("item_id",), "user_id"),
    ("item_stars", ("item_id",), "user_id"),
    ("team_members", ("team_id",), "user_id"),
    # RADD-829: directory-group memberships — the next sync would converge them
    # anyway, but a merge must not strand rows on the deleted account meanwhile.
    ("group_members", ("group_id",), "user_id"),
    ("item_participants", ("item_id",), "user_id"),
    ("form_shares", ("form_id",), "user_id"),
    # Spec 87, found by the audit: both are CASCADE, so a merge that
    # DELETES the source (as it now does) silently destroyed them instead of
    # transferring. Merging an account must not cost the person their granted
    # roles or the teams they manage.
    ("team_managers", ("team_id",), "user_id"),
    # `space_id` joined the uniqueness key when a space became a scope
    # (RADD-791). `tests/test_merge_coverage.py` caught its absence, which is the
    # test earning its keep: without it a merge would repoint a space grant onto
    # a duplicate key and 500 mid-merge, or silently keep both.
    ("global_role_grants", ("role_id", "project_id", "space_id"), "user_id"),
    # dashboard_shares is gone — dashboard sharing lives in access_grants now
    # (spec 92 adopters), which `_repoint_user_access_grants` already handles
    # generically for EVERY resource type. Same reason view_shares isn't here.
)
# Credentials/preferences are identity-private — the target keeps its own.
_MERGE_PURGE: tuple[str, ...] = ("sessions", "api_tokens", "user_totp", "notification_prefs")

# RADD-784: what dies with the account on a HARD DELETE, successor or not.
# `_MERGE_DEDUPE` transfers these (a merge asserts one person, so access
# unions); a delete must not — access exists because someone GRANTED it, and a
# deletion is not a grant. The dialog promises content; this list is everything
# that is access or personal state instead: memberships, roles, delegation,
# shares, subscriptions, the inbox. Deleted explicitly rather than left to FK
# cascade so the behaviour is written down, not implied by schema options.
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
    from sqlalchemy import text as sql

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
    """Find-or-create a PASSWORD-LESS account for someone an importer named.

    The public seam behind Jira's placeholder people (spec 90 follow-up): an
    importer must never hand-build a `User` row, and must never silently credit
    an unknown author to whoever ran the import.

    ACTIVE, because the items service refuses an inactive assignee; password-less,
    because a placeholder must not be a way in. Returns (user, created) and is
    idempotent on email, so a re-import adopts the row it made last time.
    """
    # Deferred: `get_user_by_email` is users-CRUD and stays in service.py, which
    # imports this module to re-export lifecycle functions — a top-level import
    # here would circle straight back into service.py mid-initialization.
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
    """Fold `source` into `target`: every reference (items, comments, worklogs,
    watchers, memberships, history…) repoints to the target, then the source
    row is DELETED — no shell survives (RADD-869: this docstring promised a
    deactivated audit shell the code never kept). The surviving audit record is
    the `user.deleted` event, whose payload names both accounts."""
    from sqlalchemy import text as sql

    # Deferred: see `ensure_imported_user`'s comment.
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
    # A merge asserts these two rows are the SAME PERSON, so the survivor keeps
    # that person's standing — their privileges must not depend on which row
    # happened to win. Without this, folding an admin into a member (the normal
    # direction when an AD import adopts a local account) silently demotes them,
    # and if that was the only admin the instance is left with no way back in
    # short of direct database access.
    if InstanceRole(source.instance_role) is InstanceRole.ADMIN:
        target.instance_role = InstanceRole.ADMIN.value
    await session.flush()

    # The source is DELETED, not deactivated. Everything it owned has
    # just moved to the target, so the row holds nothing; keeping a dead duplicate
    # of the same person around only cluttered pickers and left "who is this?"
    # accounts behind every AD adoption.
    #
    # Note this is NOT `delete_user`: that destroys worklogs first, on the spec-89
    # principle that nobody should be credited with hours they didn't work. That
    # protects a delete-and-reassign, which hands one person's work to ANOTHER. A
    # merge asserts one person, so their hours follow them — `_MERGE_REPOINT` has
    # already moved the worklogs above, and the row it deletes has none left.
    #
    # Emitted BEFORE the delete: the trail keeps the email and name of an account
    # that is about to stop existing.
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
    """What this account owns (spec 89) — drives the delete dialog's "these move
    to…" line, and answers whether a successor is needed at all.

    `worklogs` is reported separately because deletion DISCARDS it rather than
    reassigning: crediting a successor with hours they never worked would corrupt
    every timesheet and time report that includes them.
    """
    from sqlalchemy import text as sql

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
    from sqlalchemy import text as sql

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
    """HARD-delete an account, handing everything it authored to `successor_id`
    (spec 89). Returns the summary of what moved.

    The row really goes — as it does in `merge_users` (both end in deletion;
    the difference is a successor's CONSENT gaps are checked here, while a
    merge repoints onto an account that already owns the identity). Everything
    that would block that (13 FK columns with NO ACTION) is
    repointed first, personal state (sessions, tokens, MFA, prefs, stars,
    memberships, shares) dies with the account via purge or FK CASCADE, and
    worklogs are DELETED rather than reassigned so nobody is credited with hours
    they did not work.
    """
    from sqlalchemy import text as sql

    # Deferred: see `ensure_imported_user`'s comment.
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
        # RADD-784: the viability gate. Access does not transfer (below), so
        # the successor must already HOLD at least what the account holds —
        # otherwise the deletion is refused naming exactly what is missing,
        # and the admin grants it deliberately or picks someone else.
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
    # RADD-783: federated identities are DESTROYED, never inherited.
    #
    # `user_identities` sits in `_MERGE_REPOINT` because for a MERGE it belongs
    # there — folding a duplicate into the real account must not cost either
    # door its ability to open. But a delete is not a merge. The person is gone
    # and their work goes to a successor; their CREDENTIALS must not.
    #
    # Left in the repoint list, the deleted account's (provider, subject) pair
    # was handed to the successor, so the next SSO login with the deleted
    # address signed in AS the successor — a live account takeover by anyone who
    # still controls that IdP subject. Same shape of argument as worklogs, one
    # step more serious: crediting the wrong hours corrupts a report, inheriting
    # a credential hands over an account.
    await session.execute(sql("DELETE FROM user_identities WHERE user_id = :u"), {"u": user_id})
    # RADD-784: ACCESS DIES WITH THE ACCOUNT, successor or not. This loop used
    # to be the merge dedupe+repoint, which quietly added the successor to
    # every project the leaver was in, at the leaver's role, handed over their
    # role grants, teams and shares — and nothing in the dialog said so. The
    # same argument as RADD-783's credentials, on a slower fuse. The viability
    # gate above is the flip side: since nothing transfers, the successor must
    # already hold enough to inherit the content.
    for table, column in _DELETE_WITH_ACCOUNT:
        await session.execute(sql(f"DELETE FROM {table} WHERE {column} = :u"), {"u": user_id})
    # A gone user's access grants (view shares / user-subject field grants) go
    # too — for a MERGE they repoint (`_repoint_user_access_grants`); a delete
    # never hands them over.
    await session.execute(
        sql("DELETE FROM access_grants WHERE subject_type='user' AND subject_id = :u"),
        {"u": user_id},
    )
    if successor is not None:
        # Content + attribution only: the authored-work columns. The dedupe
        # tables no longer transfer — every one of them was access or personal
        # state, which the loop above has already destroyed. Team OWNERSHIP is
        # excluded with them: running a team is delegation, not content, so the
        # column's ON DELETE SET NULL leaves the team awaiting a deliberately
        # chosen new owner (a merge still repoints it — one person).
        for table, column in _MERGE_REPOINT:
            if (table, column) == ("teams", "owner_id"):
                continue
            await session.execute(
                sql(f"UPDATE {table} SET {column} = :dst WHERE {column} = :src"),
                {"src": user_id, "dst": successor.id},
            )
    else:
        # No successor: the account authored nothing, but it can still be
        # referenced by columns that carry NO foreign key (events.actor_id,
        # notifications) — those would silently dangle rather than error,
        # leaving the UI resolving a ghost. The audit link is nulled; the
        # user.deleted event below keeps the email/name, so the trail survives
        # without pointing at a missing row.
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
