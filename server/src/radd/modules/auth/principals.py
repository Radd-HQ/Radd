"""Credential-aware principal checks, and the BUILT-IN account rows: the two
PRINCIPALS (spec 121) and the Automation account (RADD-1499).

Anyone and Signed-in users are seeded `users` rows (fixed ids,
`UserSource.PRINCIPAL`) that act as grant SUBJECTS: a role granted to Anyone
makes a project public; one granted to Signed-in users lets any account
contribute. The union with an actor's own subjects happens in exactly two
places — `grants._subject_condition` and `SubjectContext.subject_user_ids`.
They are real rows because every resolver takes a User; they can never sign
in, receive mail, be picked, assigned or report.

The Automation account (`types.SYSTEM_ACTOR_ID`) is the row integrations write
as and author-less automations run as: a SERVICE account (key-only, no login,
no mail, badged in pickers) that is instance-admin so authz never blocks it.

All three are converged at startup and by `radd.seed`
(`ensure_builtin_accounts`), and none can be edited, deleted or merged
(`require_not_builtin`): a deactivated or demoted Automation fails every
connector write at authz with nothing saying why.
"""

import uuid

from radd.exceptions import ConflictError, ForbiddenError

from .models import User
from .types import (
    SYSTEM_ACTOR_EMAIL,
    SYSTEM_ACTOR_ID,
    SYSTEM_ACTOR_NAME,
    AuthEntity,
    InstanceRole,
    Permission,
    UserSource,
)

#: The world: every request holds this subject's grants, signed in or not.
ANYONE_ID = uuid.UUID("00000000-0000-0000-0000-000000a4104e")
#: Everyone with an account: every authenticated request holds these grants too.
SIGNED_IN_ID = uuid.UUID("00000000-0000-0000-0000-0000005160ed")

PRINCIPAL_IDS: frozenset[uuid.UUID] = frozenset({ANYONE_ID, SIGNED_IN_ID})

#: Seed shape of every built-in row: (id, email, name, source, instance role).
#: The principals' addresses are in the reserved `.invalid` TLD (RFC 2606) —
#: nothing can ever deliver to them; the Automation account is a service
#: account, which the mailer never writes to either.
BUILTIN_ROWS: tuple[tuple[uuid.UUID, str, str, UserSource, InstanceRole], ...] = (
    (ANYONE_ID, "anyone@principals.invalid", "Anyone", UserSource.PRINCIPAL, InstanceRole.MEMBER),
    (
        SIGNED_IN_ID,
        "signed-in@principals.invalid",
        "Signed-in users",
        UserSource.PRINCIPAL,
        InstanceRole.MEMBER,
    ),
    (SYSTEM_ACTOR_ID, SYSTEM_ACTOR_EMAIL, SYSTEM_ACTOR_NAME, UserSource.SERVICE, InstanceRole.ADMIN),
)

BUILTIN_IDS: frozenset[uuid.UUID] = frozenset(row[0] for row in BUILTIN_ROWS)


def is_principal(user: User | None) -> bool:
    """One of the two principal rows (never a person)."""
    return user is not None and user.id in PRINCIPAL_IDS


def is_builtin(user: User | None) -> bool:
    """A seeded row — a principal or the Automation account (RADD-1499)."""
    return user is not None and user.id in BUILTIN_IDS


def require_not_builtin(user: User, *, what: str) -> None:
    """Refuse (409) to edit, delete or merge a built-in account: its meaning is
    seeded and converged at startup, so the change would not last — and a
    deactivated Automation fails every connector write at authz."""
    if is_builtin(user):
        raise ConflictError(
            AuthEntity.USER, reason=f"{user.name} is a built-in account and cannot be {what}"
        )


def is_anonymous(user: User | None) -> bool:
    """The request carries no credential: it is acting as Anyone."""
    return user is not None and user.id == ANYONE_ID


def subject_user_ids(user_id: uuid.UUID | None) -> frozenset[uuid.UUID]:
    """The user-subject ids an actor matches on a grant table.

    Anyone's grants reach every actor; Signed-in users' grants reach every
    REAL account (a request that authenticated, by cookie or key). The Anyone
    row itself holds only its own grants — the world is never "signed in".
    `None` (no actor at all, pure fixtures) matches nothing.
    """
    if user_id is None:
        return frozenset()
    if user_id == ANYONE_ID:
        return frozenset({ANYONE_ID})
    return frozenset({user_id, ANYONE_ID, SIGNED_IN_ID})


def is_instance_admin(user: User) -> bool:
    """An active admin whose credential permits the administrative bypass."""
    if not getattr(user, "active", True) or user.instance_role != InstanceRole.ADMIN:
        return False
    scope = getattr(user, "token_scope", None)
    return scope is None or Permission.GLOBAL_MANAGE in scope.allowed(None)


def require_account_session(user: User) -> None:
    """Credentials and account security are managed through a human session.

    A key must never mint a replacement with broader scope or a later expiry,
    change MFA, or revoke another credential belonging to its account.
    Internal callers provisioning service-account keys have no API principal.
    """
    if getattr(user, "api_token_id", None) is not None or user.token_scope is not None:
        raise ForbiddenError("account security requires a browser session")


def require_person(user: User, *, what: str) -> None:
    """Refuse a principal row where a PERSON is meant (assignee, reporter,
    watcher, mention target)."""
    if is_principal(user):
        raise ForbiddenError(f"{user.name} is a principal, not a person — it cannot be {what}")


async def ensure_builtin_accounts(session) -> None:
    """Idempotently seed the built-in rows (startup ensure + `radd.seed` both
    call this, the `ensure_builtin_roles` shape). Converges name, source,
    active and role so a row edited by hand — or seeded by an older migration
    with the column default, as the Automation account was (RADD-1499) —
    returns to its seeded meaning."""
    for row_id, email, name, source, role in BUILTIN_ROWS:
        row = await session.get(User, row_id)
        if row is None:
            session.add(
                User(
                    id=row_id,
                    email=email,
                    name=name,
                    password_hash=None,
                    instance_role=role.value,
                    active=True,
                    source=source.value,
                )
            )
            continue
        row.name = name
        row.active = True
        row.source = source.value
        row.instance_role = role.value
    await session.flush()


def require_key_permission(user: User, permission: Permission, project_id: uuid.UUID | None = None) -> None:
    """Intrinsic account rights remain bounded by an explicitly scoped credential."""
    if not key_allows(user, permission, project_id):
        raise ForbiddenError(f"API key scope requires {permission}")


def key_allows(user, permission, project_id=None):
    scope = getattr(user, "token_scope", None)
    return scope is None or bool(scope.narrow(frozenset({permission}), project_id))
