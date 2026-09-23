"""RADD-1279 — an instance can REQUIRE a second factor.

Spec 48 shipped TOTP as self-service opt-in: `totp_required` answers whether
a person ENROLLED, and no policy existed to ask. This module is the policy:

- `require_mfa` (instance setting, owned here) — read by `create_session`,
  the seam every login path passes, which refuses a `LoginMethod.PASSWORD`
  session while it is on. LDAP and SSO are untouched: the IdP owns MFA there.
- the ENROLMENT TICKET a refused login receives instead of a cookie. The
  refused person holds no session, and every self-service TOTP endpoint takes
  `CurrentUser`, so without a ticket "enrol before you get in" is
  inexpressible. It opens only `/auth/mfa-enrollment/{setup,confirm}`, is
  short-lived, and the confirm that mints the session burns it.
- the admin's half: who is enrolled, and a reset for the person who lost
  both their authenticator and their recovery codes — without it,
  enforcement turns a rare annoyance into a lockout.
- the switch's guard: it cannot be turned on by an admin who would be
  locked out by it.
"""

import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError, UnauthorizedError
from radd.modules.events import service as events

from . import security
from .models import MfaEnrollmentTicket, TotpRecoveryCode, User, UserTotp
from .types import AuthEntity, AuthEvent

#: The 401 detail the login form keys on to switch to enrolment.
MFA_ENROLLMENT_REQUIRED = "mfa_enrollment_required"
TICKET_EXPIRED = "that enrolment link has expired — sign in again"


class MfaEnrollmentRequired(UnauthorizedError):
    """Raised by `create_session`. A 401 wherever it escapes uncaught, so a
    login path that forgets to hand out a ticket still fails CLOSED; `/login`
    catches it and answers with the ticket."""

    def __init__(self, user: User):
        self.user = user
        super().__init__(MFA_ENROLLMENT_REQUIRED)


async def required(session: AsyncSession) -> bool:
    """Is the instance policy on? Deferred import: `settings` depends on auth
    (a weak edge the other way, declared in the manifest)."""
    from radd.modules.settings import service as settings_service
    from radd.modules.settings.types import SettingKey

    return bool(await settings_service.resolve(session, SettingKey.REQUIRE_MFA))


async def is_enrolled(session: AsyncSession, user_id: uuid.UUID) -> bool:
    row = await session.get(UserTotp, user_id)
    return row is not None and row.confirmed_at is not None


async def enrolled_ids(session: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these people hold a CONFIRMED enrolment — one query for a page."""
    if not user_ids:
        return set()
    rows = await session.scalars(
        select(UserTotp.user_id).where(
            UserTotp.user_id.in_(user_ids), UserTotp.confirmed_at.is_not(None)
        )
    )
    return set(rows)


# --- the enrolment ticket ---


async def issue_ticket(session: AsyncSession, user: User) -> str:
    """A fresh ticket; any earlier unused one for this person dies with it, so
    only the most recent login's hand-off works."""
    await session.execute(
        delete(MfaEnrollmentTicket).where(MfaEnrollmentTicket.user_id == user.id)
    )
    raw = security.new_session_token()
    session.add(
        MfaEnrollmentTicket(
            user_id=user.id,
            token_hash=security.hash_token(raw),
            expires_at=security.utcnow()
            + timedelta(minutes=settings.mfa_enrollment_ticket_minutes),
        )
    )
    await session.flush()
    return raw


async def _live_ticket(session: AsyncSession, raw: str) -> MfaEnrollmentTicket:
    row = await session.scalar(
        select(MfaEnrollmentTicket).where(
            MfaEnrollmentTicket.token_hash == security.hash_token(raw),
            MfaEnrollmentTicket.used_at.is_(None),
            MfaEnrollmentTicket.expires_at > security.utcnow(),
        )
    )
    if row is None:
        raise UnauthorizedError(TICKET_EXPIRED)
    return row


async def user_for_ticket(session: AsyncSession, raw: str) -> User:
    """The account a live ticket speaks for — uniform 401 otherwise."""
    row = await _live_ticket(session, raw)
    user = await session.get(User, row.user_id)
    if user is None or not user.active:
        raise UnauthorizedError(TICKET_EXPIRED)
    return user


async def burn_ticket(session: AsyncSession, raw: str) -> None:
    row = await _live_ticket(session, raw)
    row.used_at = security.utcnow()
    await session.flush()


# --- the admin's half ---


async def admin_reset(session: AsyncSession, *, admin: User, target: User) -> None:
    """Remove someone's enrolment and recovery codes. Their next password
    login is a first enrolment (or no second factor, with the policy off)."""
    row = await session.get(UserTotp, target.id)
    if row is None:
        raise ConflictError(AuthEntity.USER, reason=f"{target.email} has no MFA enrolment")
    await session.execute(delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == target.id))
    await session.delete(row)
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.MFA_RESET,
        entity_type=AuthEntity.USER,
        entity_id=target.id,
        actor_id=admin.id,
        payload={"admin": admin.email, "target": target.email},
    )


async def guard_require_mfa(session: AsyncSession, value: object, actor_id: uuid.UUID | None) -> None:
    """`SettingSpec.guard` for `require_mfa`: turning it ON is refused while the
    acting admin has no confirmed enrolment — the switch must not lock out the
    person flipping it. Off is always allowed."""
    if not value or actor_id is None:
        return
    actor = await session.get(User, actor_id)
    if actor is None or actor.password_hash is None:
        # An SSO/LDAP-only admin is not gated by the policy they are setting.
        return
    if not await is_enrolled(session, actor_id):
        raise ConflictError(
            "scoped_setting",
            reason=(
                "set up two-factor authentication on your own account first "
                "(Settings → Profile) — turning this on would otherwise lock you out"
            ),
        )
