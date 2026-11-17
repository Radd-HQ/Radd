"""Requests that change something must come from this instance (RADD-1547).

The session is a cookie with `SameSite=Lax`. That keeps another SITE from
sending it with a write, but a site is a registrable domain: every other origin
under the same one — another service on a sibling subdomain, a page someone can
script there — is same-site, and its requests arrive with the cookie. Nothing
checked where a write came from, and neither WebSocket endpoint looked at the
handshake's `Origin`.

The rule, for a request that carries the session cookie and no `Authorization`
header (a bearer token is never attached by a browser on its own):

- an unsafe method, or a WebSocket handshake, with an `Origin` → it must be the
  request's own host, `app_base_url`, or listed in `trusted_origins`;
- no `Origin` but a `Sec-Fetch-Site` → `same-origin` or `none` passes;
- neither header → served. That is a script or curl, not a browser being steered.

A refusal is a 403 that names the setting; a refused socket is closed before it
is accepted.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from radd.config import settings

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SESSION_COOKIE = "radd_session"  # auth.types.SESSION_COOKIE_NAME; the kernel imports no module
#: `Sec-Fetch-Site` values a browser sends for a request this instance's own page made,
#: or that a person started themselves (typed address, bookmark).
_OWN_FETCH_SITES = frozenset({"same-origin", "none"})
_WS_POLICY_VIOLATION = 1008


def _origin_of(url: str) -> str | None:
    """`scheme://host[:port]`, lower-cased, or None for something that is not one."""
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _trusted() -> set[str]:
    origins = {_origin_of(settings.app_base_url)}
    origins.update(_origin_of(entry) for entry in settings.trusted_origins.split(",") if entry.strip())
    origins.discard(None)
    return origins  # type: ignore[return-value]


def allowed(headers: dict[bytes, bytes]) -> bool:
    """Whether a cookie-authenticated write (or socket) with these headers came
    from this instance."""
    origin = headers.get(b"origin", b"").decode("latin-1").strip()
    if origin and origin != "null":
        claimed = _origin_of(origin)
        if claimed is None:
            return False
        # The request's own host: whatever scheme the proxy in front speaks, an
        # Origin naming the host this request was addressed to is this instance.
        host = headers.get(b"host", b"").decode("latin-1").strip().lower()
        if host and claimed.split("://", 1)[1] == host:
            return True
        return claimed in _trusted()
    if origin == "null":
        return False  # a sandboxed frame or a redirect chain: never this instance's page
    fetch_site = headers.get(b"sec-fetch-site", b"").decode("latin-1").strip().lower()
    if fetch_site:
        return fetch_site in _OWN_FETCH_SITES
    return True


def _has_session(headers: dict[bytes, bytes]) -> bool:
    cookie = headers.get(b"cookie", b"").decode("latin-1")
    return any(part.strip().startswith(f"{_SESSION_COOKIE}=") for part in cookie.split(";"))


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket") or not settings.origin_check:
            await self.app(scope, receive, send)
            return
        if kind == "http" and scope.get("method", "GET").upper() in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or ())
        if b"authorization" in headers or not _has_session(headers) or allowed(headers):
            await self.app(scope, receive, send)
            return
        if kind == "websocket":
            await send({"type": "websocket.close", "code": _WS_POLICY_VIOLATION})
            return
        response = JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "this request came from another origin and was refused. If that origin "
                    "is this instance under another address, add it to RADD_TRUSTED_ORIGINS."
                )
            },
        )
        await response(scope, receive, send)
