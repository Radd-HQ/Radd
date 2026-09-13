"""Sign-in endpoints (spec 40 → spec 110): provider list, redirect, callback.

The callback returns a REDIRECT even when it refuses, because this leg runs in a
browser address bar: a raw 403 JSON body is what a person sees, and "you can't
sign up from this domain" is a message they need to read on the login page. The
reason travels as a query parameter, never a cookie.
"""

import logging
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError, RaddError
from radd.modules.auth import service as auth_service
from radd.modules.auth.types import SESSION_COOKIE_NAME

from . import registry, service
from .models import SsoProvider
from .schemas import SsoProviderPublic
from .types import OIDC_FLOW_COOKIE, OIDC_FLOW_TTL_SECONDS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["sso"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/sso/providers", response_model=list[SsoProviderPublic])
async def public_providers(session: Session) -> list[SsoProviderPublic]:
    """UNAUTHENTICATED — the login page's buttons. Only enabled, fully-configured
    rows, and only their label/kind: never a client id, issuer or policy."""
    return [
        SsoProviderPublic(id=p.id, name=p.name, kind=p.kind)
        for p in await registry.list_providers(session)
        if p.enabled and registry.configured(p)
    ]


async def _resolve_provider(session: AsyncSession, provider_id: uuid.UUID | None) -> SsoProvider:
    """Pick the provider to start a flow with. A missing id resolves to the only
    configured provider, which keeps single-IdP instances (and spec 40's bare
    `/auth/oidc/login` link) working untouched."""
    usable = [p for p in await registry.list_providers(session) if p.enabled and registry.configured(p)]
    if not usable:
        raise ForbiddenError("no sign-in provider is configured")
    if provider_id is None:
        if len(usable) > 1:
            raise ForbiddenError("several sign-in providers exist — choose one")
        return usable[0]
    for provider in usable:
        if provider.id == provider_id:
            return provider
    raise ForbiddenError("that sign-in provider is unavailable")


@router.get("/oidc/login")
async def oidc_login(
    session: Session, provider_id: uuid.UUID | None = None, next: str | None = None
) -> RedirectResponse:
    """Kick off the code+PKCE flow: park state/nonce/verifier/provider in a
    short-lived HttpOnly cookie and bounce to the provider. `next` (spec 121)
    is the same-origin page to return to — it rides the flow cookie, the only
    state that survives the round trip."""
    provider = await _resolve_provider(session, provider_id)
    flow = service.new_flow(provider)
    flow["next"] = service.safe_next_path(next)
    response = RedirectResponse(await service.authorization_url(provider, flow), status_code=307)
    response.set_cookie(
        OIDC_FLOW_COOKIE,
        service.flow_cookie_value(flow),
        max_age=OIDC_FLOW_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
    return response


def _refused(message: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?sso_error={quote(message)}", status_code=307)
    response.delete_cookie(OIDC_FLOW_COOKIE)
    return response


@router.get("/oidc/callback")
async def oidc_callback(code: str, state: str, request: Request, session: Session):
    flow = service.parse_flow_cookie(request.cookies.get(OIDC_FLOW_COOKIE, ""), OIDC_FLOW_TTL_SECONDS)
    if flow is None or flow.get("state") != state:
        return _refused("That sign-in attempt expired. Please try again.")
    try:
        provider = await _resolve_provider(session, uuid.UUID(flow["provider_id"]))
        claims = await service.exchange_code(provider, code, flow)
        user = await service.provision(session, provider, claims)
    except RaddError as exc:
        # Policy refusals (unknown domain, deactivated account, unverified email)
        # are the expected outcome here, not a server fault — the person reads
        # the reason and acts on it.
        return _refused(str(exc))
    except Exception:
        logger.exception("sso: callback failed")
        return _refused("Sign-in failed. Contact an administrator if it continues.")

    token = await auth_service.create_session(session, user)
    response = RedirectResponse(service.safe_next_path(flow.get("next")) or "/", status_code=307)
    response.delete_cookie(OIDC_FLOW_COOKIE)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
    return response
