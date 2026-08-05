"""Reconciling an AD user import against accounts that already exist (spec 88).

The problem this solves: Radd identifies people by EMAIL, but accounts arrive
from several places — the Jira importer, local signup, an older domain — so the
same human is often already present under a different address. Importing from AD
blindly then mints a second account and splits their history in two.

So the import is two steps. `plan_user_import` (pure, unit-tested) classifies
every incoming directory user against the existing roster; the admin resolves
each conflict; `apply_resolution` executes the choice. Both write verbs end with
the DIRECTORY as the source of truth — they differ only in how many Radd
accounts are involved:

- OVERWRITE — one account. Its email/name become AD's and its `id` is preserved,
  so every issue, comment and worklog stays attached to the same person.
- MERGE — two accounts. The look-alike is folded into the AD-identified one via
  the existing `merge_users`, then the survivor takes AD's values.

Matching deliberately never happens automatically: a name collision is a
heuristic ("James Smith" is two people often enough), and silently rewriting an
account's email address is not something to infer.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import UserSource

from . import service
from .types import (
    DirectoryUser,
    ImportMatchKind,
    ImportResolution,
    ImportStatus,
    LdapEntity,
)


@dataclass(frozen=True)
class ExistingMatch:
    """One account the incoming directory user might already be."""

    user_id: uuid.UUID
    email: str
    name: str
    source: str
    active: bool
    kind: ImportMatchKind


@dataclass(frozen=True)
class ImportCandidate:
    """One incoming directory user, classified against the existing roster."""

    username: str
    email: str
    name: str
    status: ImportStatus
    matches: tuple[ExistingMatch, ...]
    suggested: ImportResolution


def _local_part(email: str) -> str:
    return email.split("@", 1)[0].strip().lower()


def plan_user_import(
    directory_users: Iterable[DirectoryUser], existing: Iterable[User]
) -> list[ImportCandidate]:
    """Directory truth × the existing roster → per-person classification (pure).

    An exact email match is the account, full stop. Anything else — the AD
    username equalling an existing email's local part, or an identical display
    name — is a *candidate* duplicate under a different address, which is exactly
    the case that silently creates a second account today.
    """
    roster = list(existing)
    by_email = {user.email.lower(): user for user in roster}
    by_local: dict[str, list[User]] = {}
    by_name: dict[str, list[User]] = {}
    for user in roster:
        by_local.setdefault(_local_part(user.email), []).append(user)
        name = user.name.strip().lower()
        if name:
            by_name.setdefault(name, []).append(user)

    candidates: list[ImportCandidate] = []
    for directory_user in directory_users:
        email = directory_user.email.lower()
        exact = by_email.get(email)
        matches: list[ExistingMatch] = []
        if exact is not None:
            matches.append(_match(exact, ImportMatchKind.EMAIL))
        seen = {exact.id} if exact else set()

        # The AD username against existing email local parts, then the local part
        # of the AD address itself — `jsmith` vs `jsmith@old-domain.example`.
        for key in dict.fromkeys(
            [directory_user.username.strip().lower(), _local_part(directory_user.email)]
        ):
            for user in by_local.get(key, ()):
                if user.id not in seen:
                    seen.add(user.id)
                    matches.append(_match(user, ImportMatchKind.USERNAME))
        for user in by_name.get(directory_user.name.strip().lower(), ()):
            if user.id not in seen:
                seen.add(user.id)
                matches.append(_match(user, ImportMatchKind.NAME))

        look_alikes = [m for m in matches if m.kind is not ImportMatchKind.EMAIL]
        if look_alikes:
            status = ImportStatus.CONFLICT
            # Two accounts already exist -> merging is the only way to end with
            # one person; otherwise the look-alike simply adopts AD's identity.
            suggested = ImportResolution.MERGE if exact else ImportResolution.OVERWRITE
        elif exact is not None:
            status, suggested = ImportStatus.LINKED, ImportResolution.OVERWRITE
        else:
            status, suggested = ImportStatus.NEW, ImportResolution.CREATE
        candidates.append(
            ImportCandidate(
                username=directory_user.username,
                email=directory_user.email,
                name=directory_user.name,
                status=status,
                matches=tuple(matches),
                suggested=suggested,
            )
        )
    return candidates


def _match(user: User, kind: ImportMatchKind) -> ExistingMatch:
    return ExistingMatch(
        user_id=user.id,
        email=user.email,
        name=user.name,
        source=user.source,
        active=user.active,
        kind=kind,
    )


# --- applying one resolution --------------------------------------------------


async def adopt_directory_identity(
    session: AsyncSession, user: User, directory_user: DirectoryUser
) -> bool:
    """Make an existing account BE the directory account: its email and name
    become AD's and it is marked `source=ldap`. Returns whether anything changed.

    The row's `id` never moves, which is the entire point — the person keeps
    their issues, comments and worklogs. The password hash is deliberately left
    alone: clearing it would lock out anyone mid-migration who still signs in
    locally, and the directory login path keys on email regardless.
    """
    changed = False
    if user.email != directory_user.email:
        clash = await auth_service.get_user_by_email(session, directory_user.email)
        if clash is not None and clash.id != user.id:
            raise ConflictError(
                LdapEntity.LDAP,
                reason=(
                    f"{directory_user.email} already belongs to another account "
                    f"({clash.name}) — merge them instead of overwriting"
                ),
            )
        user.email = directory_user.email
        changed = True
    if directory_user.name and user.name != directory_user.name:
        user.name = directory_user.name
        changed = True
    if user.source != UserSource.LDAP:
        # Now an AD-governed account: the user sync may rename it, and (if the
        # deactivate-missing toggle is on) deactivate it when they leave AD.
        user.source = UserSource.LDAP
        changed = True
    if changed:
        await session.flush()
    return changed


async def apply_resolution(
    session: AsyncSession,
    directory_user: DirectoryUser,
    resolution: ImportResolution,
    target_user_id: uuid.UUID | None,
    actor_id: uuid.UUID | None = None,
) -> tuple[User | None, bool]:
    """Execute one admin decision. Returns (resulting user, created)."""
    if resolution is ImportResolution.SKIP:
        return None, False

    if resolution is ImportResolution.CREATE:
        # Explicitly keeping the look-alike: create-or-link on the email alone.
        return await service.find_or_create_user(session, directory_user)

    if target_user_id is None:
        raise ConflictError(
            LdapEntity.LDAP, reason=f"{resolution} needs the account it applies to"
        )
    look_alike = await auth_service.get_user(session, target_user_id)

    if resolution is ImportResolution.OVERWRITE:
        await adopt_directory_identity(session, look_alike, directory_user)
        return look_alike, False

    # MERGE: the AD-identified account survives and absorbs the look-alike —
    # `merge_users(source, target)` folds source INTO target, so the look-alike
    # is the source and the directory account is the target. It is created first
    # when the AD address isn't here yet, so "merge" works even in the
    # one-account case (though overwrite is preferable there: it keeps the id).
    survivor, created = await service.find_or_create_user(session, directory_user)
    if survivor.id == look_alike.id:
        raise ConflictError(
            LdapEntity.LDAP,
            reason=f"{look_alike.email} is already the directory account — nothing to merge",
        )
    # A deactivated survivor is allowed: the work still repoints to the right
    # person, and whether that person should have access is a separate decision
    # (reactivate them on the Users page). The reconcile report flags the case so
    # it is visible rather than surprising.
    await auth_service.merge_users(session, look_alike.id, survivor.id, actor_id=actor_id)
    await adopt_directory_identity(session, survivor, directory_user)
    return survivor, created
