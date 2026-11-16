"""RADD-1529 routes: a person changes their own password; an admin resets someone else's."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session

from . import authz, passwords, service
from .deps import CurrentUser
from .principals import require_account_session
from .schemas import PasswordAdminSet, PasswordChange, PasswordChangeResult
from .throttle import check_login_attempt
from .types import SESSION_COOKIE_NAME

password_router = APIRouter(prefix="/auth", tags=["auth"])
password_admin_router = APIRouter(prefix="/users", tags=["users"])

Session = Annotated[AsyncSession, Depends(get_session)]


@password_router.post("/password", response_model=PasswordChangeResult)
async def change_my_password(
    data: PasswordChange, session: Session, user: CurrentUser, request: Request
) -> PasswordChangeResult:
    """Change your own password. Needs the current one and a browser session — a
    key must not be able to lock its owner out. Your other sessions are signed out."""
    require_account_session(user)
    # The current password is a guessable secret: the login throttle applies.
    check_login_attempt(request, user.email)
    ended = await passwords.change_own(
        session,
        user,
        current_password=data.current_password,
        new_password=data.new_password,
        keep_token_hash=passwords.token_hash_of(request.cookies.get(SESSION_COOKIE_NAME)),
    )
    return PasswordChangeResult(sessions_ended=ended)


@password_admin_router.put("/{user_id}/password", response_model=PasswordChangeResult)
async def set_user_password(
    user_id: uuid.UUID, data: PasswordAdminSet, session: Session, actor: CurrentUser
) -> PasswordChangeResult:
    """Set a new password for a local account and sign it out everywhere. Audited
    as `auth.password_reset`; tell the person the new password out of band."""
    require_account_session(actor)
    await authz.require(session, actor, authz.Permission.USER_MANAGE)
    target = await service.get_user(session, user_id)
    ended = await passwords.admin_set(
        session, admin=actor, target=target, new_password=data.new_password
    )
    return PasswordChangeResult(sessions_ended=ended)
