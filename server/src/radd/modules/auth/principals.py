"""Credential-aware principal checks shared by all administrative surfaces —
and, since spec 121, the two PRINCIPAL rows that stand for "the world".

## Anyone and Signed-in users (RADD-1142)

Two seeded `users` rows with fixed ids and `UserSource.PRINCIPAL`. They are
grant SUBJECTS, not people: a role granted to *Anyone* on a project is what
makes that project public, a role granted to *Signed-in users* is what lets
anyone with an account contribute there. Every actor holds Anyone's grants;
every real account additionally holds Signed-in users' grants. That union is
made in exactly two places — `grants._subject_condition` for role grants and
`SubjectContext.subject_user_ids` for access grants — so nothing downstream
(`effective_permissions`, `readable_projects`, the relation filter, the MCP
catalog) learns that the world exists. It is one more subject.

An unauthenticated request resolves to the Anyone row at the auth seam
(`deps.actor`), which is why it must be a real `User` row rather than a
sentinel object: every resolver takes a User, and a public project's reads
must go through the same code as a member's. The row can never log in
(`create_session` refuses PRINCIPAL like SERVICE and EMAIL), never receives
mail, never appears in a picker, and is refused as an assignee or reporter.

The ids are fixed so a migration can seed them and a fresh `seed` can
converge on the same rows; the SYSTEM actor (`automations.types`) set the
precedent.
"""

import uuid

from radd.exceptions import ForbiddenError

from .models import User
from .types import InstanceRole, Permission, UserSource

#: The world: every request holds this subject's grants, signed in or not.
ANYONE_ID = uuid.UUID("00000000-0000-0000-0000-000000a4104e")
#: Everyone with an account: every authenticated request holds these grants too.
SIGNED_IN_ID = uuid.UUID("00000000-0000-0000-0000-0000005160ed")

PRINCIPAL_IDS: frozenset[uuid.UUID] = frozenset({ANYONE_ID, SIGNED_IN_ID})

#: Seed shape for the two rows: (id, email, name). The addresses are in the
#: reserved `.invalid` TLD (RFC 2606) — nothing can ever deliver to them.
PRINCIPAL_ROWS: tuple[tuple[uuid.UUID, str, str], ...] = (
    (ANYONE_ID, "anyone@principals.invalid", "Anyone"),
    (SIGNED_IN_ID, "signed-in@principals.invalid", "Signed-in users"),
)


def is_principal(user: User | None) -> bool:
    """One of the two principal rows (never a person)."""
    return user is not None and user.id in PRINCIPAL_IDS


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


async def ensure_principals(session) -> None:
    """Idempotently seed the two rows (startup ensure + `radd.seed` both call
    this, the `ensure_builtin_roles` shape). Converges name/source/active so a
    row edited by hand returns to its seeded meaning."""
    for row_id, email, name in PRINCIPAL_ROWS:
        row = await session.get(User, row_id)
        if row is None:
            session.add(
                User(
                    id=row_id,
                    email=email,
                    name=name,
                    password_hash=None,
                    instance_role=InstanceRole.MEMBER.value,
                    active=True,
                    source=UserSource.PRINCIPAL.value,
                )
            )
            continue
        row.name = name
        row.active = True
        row.source = UserSource.PRINCIPAL.value
        row.instance_role = InstanceRole.MEMBER.value
    await session.flush()
