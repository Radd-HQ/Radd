"""Security response headers (RADD-1531).

The SPA renders no stored HTML, so this is a second line of defence, not a patch
for a known hole — but an app that can be framed by any site can be clickjacked.

The app sets these itself rather than leaving them to a reverse proxy because
the policy depends on what the app loads (plugin bundles, presigned downloads),
which only the app can keep true.

The Content-Security-Policy ships in REPORT-ONLY mode by default: the browser
logs what it would have blocked and blocks nothing. `RADD_CSP_MODE=enforce`
turns it on once a deployment's console is clean; `off` removes it. Framing is
the exception — `frame-ancestors` is not honoured in report-only, so it is
always sent in an enforced policy of its own.
"""

import base64
import hashlib
import re
from enum import StrEnum
from pathlib import Path

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from radd.config import settings


class CspMode(StrEnum):
    OFF = "off"
    REPORT = "report"
    ENFORCE = "enforce"


_INLINE_SCRIPT = re.compile(rb"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL)
_shell_hashes: tuple[float, tuple[str, ...]] | None = None


def inline_script_hashes(shell: bytes) -> tuple[str, ...]:
    """A CSP hash source for every inline script in the SPA shell.

    The shell carries exactly one, and it cannot move to a file: the import map
    that lets plugin remotes share the host's React must be inline. Hashing what
    the built `index.html` actually contains keeps `script-src` free of
    'unsafe-inline' and stays right across builds without anyone updating a
    constant."""
    return tuple(
        "'sha256-" + base64.b64encode(hashlib.sha256(body).digest()).decode() + "'"
        for body in _INLINE_SCRIPT.findall(shell)
    )


def _shell_script_sources() -> tuple[str, ...]:
    """The hashes for the served bundle, re-read when the file changes (a rebuild)."""
    global _shell_hashes
    web_dist = Path(settings.web_dist) if settings.web_dist else _DEFAULT_WEB_DIST
    index = web_dist / "index.html"
    try:
        modified = index.stat().st_mtime
    except OSError:
        return ()  # API-only deployment: no shell, nothing inline to allow
    if _shell_hashes is None or _shell_hashes[0] != modified:
        _shell_hashes = (modified, inline_script_hashes(index.read_bytes()))
    return _shell_hashes[1]


#: The repo's web/dist — the same default `app._mount_spa` serves.
_DEFAULT_WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


def content_security_policy() -> str:
    """What the SPA is allowed to load.

    - scripts: same origin only — the host bundle and plugin remotes under /plugins —
      plus the hash of the shell's inline import map (`inline_script_hashes`).
    - styles: same origin plus inline (React writes `style` attributes; the editor
      and charts position with them).
    - images/media: same origin, `data:`/`blob:` (pasted and previewed files), and
      https (identity-provider avatars, presigned object-storage downloads).
    - connect: same origin (HTTP and the realtime socket) and https (presigned uploads).
    - nothing may be embedded as a plugin object, and forms post only home.
    """
    return "; ".join((
        "default-src 'self'",
        " ".join(("script-src 'self'", *_shell_script_sources())),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https:",
        "media-src 'self' blob: https:",
        "font-src 'self' data:",
        "connect-src 'self' https: wss:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ))


def security_headers() -> list[tuple[str, str]]:
    """The headers for every response, from settings. Pure, so it is testable."""
    ancestors = settings.frame_ancestors.strip() or "'none'"
    headers = [
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("Content-Security-Policy", f"frame-ancestors {ancestors}"),
    ]
    if ancestors == "'none'":
        headers.append(("X-Frame-Options", "DENY"))  # for browsers that predate frame-ancestors
    if settings.app_base_url.startswith("https://"):
        # Only when the deployment says it is served over TLS: sent over plain http
        # it is ignored, and on a host that is NOT https it would lock people out.
        headers.append(("Strict-Transport-Security", f"max-age={settings.hsts_max_age_seconds}"))
    mode = CspMode(settings.csp_mode)
    if mode is CspMode.REPORT:
        headers.append(("Content-Security-Policy-Report-Only", content_security_policy()))
    elif mode is CspMode.ENFORCE:
        # One header: a browser applies every CSP it is sent, so framing joins the policy.
        headers[2] = ("Content-Security-Policy", f"{content_security_policy()}; frame-ancestors {ancestors}")
    return headers


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in security_headers():
                    # A route that set its own (attachments force a download with
                    # their own nosniff) keeps it.
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, with_headers)
