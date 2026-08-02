"""Request auth dependencies. Other modules import CurrentUser/OptionalUser from here."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import UnauthorizedError

from .models import User
from .types import PAT_PREFIX, SESSION_COOKIE_NAME

_BEARER_PREFIX = "Bearer "


async def optional_user(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> User | None:
    """Resolve the session cookie, else a `Bearer radd_pat_…` header. None if anonymous."""
    # Deferred import: every router imports CurrentUser from this module (including
    # modules that load before auth), so deps must stay import-light to avoid cycles.
    from . import service

    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie:
        user = await service.user_for_session_token(session, cookie)
        if user is not None:
            return user
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
