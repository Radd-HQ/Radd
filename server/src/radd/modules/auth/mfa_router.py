"""RADD-1279 routes: the enrolment hand-off a refused login walks, and the
admin's reset. Split from `router.py` (already past the size rule); the
policy itself lives in `mfa_policy`.

The two `/auth/mfa-enrollment/*` routes take a TICKET, never `CurrentUser`:
the person reaching them was refused a session precisely because they have no
second factor, so they hold no cookie. Confirm is the only way the ticket
turns into a session, and it burns the ticket in the same transaction.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session

from . import authz, mfa_policy, service, totp
from .deps import CurrentUser
from .schemas import (
    MfaEnrollmentConfirm,
    MfaEnrollmentTicketRequest,
    TotpRecoveryCodesRead,
    TotpSetupRead,
)
from .throttle import check_login_attempt
from .types import SESSION_COOKIE_NAME, LoginMethod

mfa_enrollment_router = APIRouter(prefix="/auth/mfa-enrollment", tags=["auth"])
mfa_admin_router = APIRouter(prefix="/users", tags=["users"])

Session = Annotated[AsyncSession, Depends(get_session)]


@mfa_enrollment_router.post("/setup", response_model=TotpSetupRead)
async def enrollment_setup(
    data: MfaEnrollmentTicketRequest, session: Session, request: Request
) -> TotpSetupRead:
    """A pending secret for the ticket's account — the same call as the
    self-service `POST /auth/totp/setup`, reached without a session."""
    user = await mfa_policy.user_for_ticket(session, data.ticket)
    check_login_attempt(request, user.email)
    row = await service.totp_setup(session, user)
    return TotpSetupRead(
        secret=row.secret, otpauth_uri=totp.provisioning_uri(row.secret, user.email)
    )


@mfa_enrollment_router.post("/confirm", response_model=TotpRecoveryCodesRead)
async def enrollment_confirm(
    data: MfaEnrollmentConfirm, session: Session, request: Request, response: Response
) -> TotpRecoveryCodesRead:
    """Confirm the code, burn the ticket, and sign the person in — returning
    the recovery codes, shown once, exactly as self-service enrolment does."""
    user = await mfa_policy.user_for_ticket(session, data.ticket)
    check_login_attempt(request, user.email)
    codes = await service.totp_confirm(session, user, data.code)
    await mfa_policy.burn_ticket(session, data.ticket)
    token = await service.create_session(session, user, method=LoginMethod.PASSWORD_TOTP)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
    return TotpRecoveryCodesRead(recovery_codes=codes)


@mfa_admin_router.delete("/{user_id}/totp", status_code=204)
async def reset_user_mfa(user_id: uuid.UUID, session: Session, actor: CurrentUser) -> None:
    """Remove one person's TOTP enrolment and recovery codes — for the account
    that lost both. Audited as `auth.mfa_reset`."""
    await authz.require(session, actor, authz.Permission.USER_MANAGE)
    target = await service.get_user(session, user_id)
    await mfa_policy.admin_reset(session, admin=actor, target=target)
