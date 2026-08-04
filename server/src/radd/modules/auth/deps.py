"""Request auth dependencies. Other modules import CurrentUser/OptionalUser from here."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError, UnauthorizedError

from .models import User
from .types import PAT_PREFIX, SESSION_COOKIE_NAME

_BEARER_PREFIX = "Bearer "

# Methods that read; anything else is refused while previewing (RADD-836 U1).
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The two writes that must survive a preview: leaving it, and logging out.
_VIEW_AS_EXEMPT_SUFFIXES = ("/auth/view-as", "/auth/logout")


async def optional_user(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> User | None:
    """Resolve the session cookie, else a `Bearer radd_pat_…` header. None if anonymous.

    RADD-836 U1 — "View as": a session carrying `view_as_user_id` resolves to
    THAT user, read-only. The guard lives here, on the resolution seam every
    endpoint shares, so no write can slip through a surface that forgot a
    check — a preview that can write is an audit-trail forgery machine. The
    real admin rides on `request.state.view_as_real` for /auth/me's banner.
    """
    # Deferred import: every router imports CurrentUser from this module (including
    # modules that load before auth), so deps must stay import-light to avoid cycles.
    from . import service

    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie:
        resolved = await service.resolve_session_users(session, cookie)
        if resolved is not None:
            real, target = resolved
            if target is not None:
                request.state.view_as_real = real
                if request.method not in _READ_METHODS and not request.url.path.endswith(
                    _VIEW_AS_EXEMPT_SUFFIXES
                ):
                    raise ForbiddenError(
                        "view-as is read-only — exit the preview to make changes"
                    )
                return target
            return real
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith(_BEARER_PREFIX):
        token = authorization[len(_BEARER_PREFIX) :].strip()
        if token.startswith(PAT_PREFIX):
            return await service.user_for_api_token(session, token)
    return None


async def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise UnauthorizedError()
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
