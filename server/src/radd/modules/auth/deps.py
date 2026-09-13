"""Request auth dependencies. Other modules import CurrentUser/OptionalUser/Actor from here."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError, UnauthorizedError

from .models import User
from .principals import ANYONE_ID, require_account_session
from .types import PAT_PREFIX, SESSION_COOKIE_NAME

_BEARER_PREFIX = "Bearer "

# Methods that read; anything else is refused while previewing (RADD-836 U1)
# and, since spec 121, refused outright for the anonymous principal.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The two writes that must survive a preview: leaving it, and logging out.
_VIEW_AS_EXEMPT_SUFFIXES = ("/auth/view-as", "/auth/logout")

#: Per-request memo of the Anyone row (`session.info`), so a page load that
#: resolves the actor several times costs one query.
_ANYONE_CACHE_KEY = "radd.anyone_user"


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
            user = await service.user_for_api_token(session, token)
            if user is not None and request.method not in _READ_METHODS:
                # Self-service account mutations have no project/atom gate.
                # Keep API keys out of this session-only security surface.
                auth_root = request.url.path.split("/auth/", 1)
                if len(auth_root) == 2 and auth_root[1] not in {"logout", "me/preferences"}:
                    require_account_session(user)
            return user
    return None


async def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise UnauthorizedError()
    return user


async def anyone_user(session: AsyncSession) -> User:
    """The Anyone principal row — what an unauthenticated request acts as (spec 121)."""
    cached: User | None = session.info.get(_ANYONE_CACHE_KEY)
    if cached is not None:
        return cached
    row = await session.get(User, ANYONE_ID)
    if row is None:
        # Not seeded (a database predating spec 121 with no migration run):
        # fail closed as "no credential", never as a synthetic principal.
        raise UnauthorizedError()
    session.info[_ANYONE_CACHE_KEY] = row
    return row


async def actor(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(optional_user)],
) -> User:
    """The acting principal, with no credential resolving to **Anyone** (spec 121).

    The read surface a public project needs declares `Actor` instead of
    `CurrentUser`; everything else keeps 401-ing. The dependency is
    STRUCTURALLY read-only: a non-read method resolving to the principal is
    refused here, the RADD-836 rule, so a route that declared `Actor` by
    mistake still cannot attribute a write to the world. The inventory of
    routes accepting it is frozen by `tests/test_anonymous_surface.py`.
    """
    if user is not None:
        return user
    if request.method not in _READ_METHODS:
        raise UnauthorizedError()
    return await anyone_user(session)


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
Actor = Annotated[User, Depends(actor)]
