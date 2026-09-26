"""Maintenance mode — a core switch, not a backup feature: while engaged, every request
answers 503 except the backup status/run endpoints, so a restore can be watched to the end."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

#: Paths that stay live during maintenance (prefix match, after the API prefix).
ALLOWED_PREFIXES = ("/backups/status", "/backups/runs")


@dataclass
class MaintenanceState:
    active: bool = False
    reason: str = ""
    since: datetime | None = None


_state = MaintenanceState()


def state() -> MaintenanceState:
    return _state


def is_active() -> bool:
    return _state.active


def engage(reason: str) -> None:
    _state.active = True
    _state.reason = reason
    _state.since = datetime.now(UTC)
    logger.warning("maintenance mode ENGAGED: %s", reason)


def release() -> None:
    if _state.active:
        logger.warning("maintenance mode released after %s", _state.reason)
    _state.active = False
    _state.reason = ""
    _state.since = None


class MaintenanceMiddleware(BaseHTTPMiddleware):
    """503 for everything but the allowlist while maintenance is engaged."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        if _state.active and not _is_allowed(request.url.path):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": _state.reason or "Radd is in maintenance mode",
                    "maintenance": True,
                    "since": _state.since.isoformat() if _state.since else None,
                },
                headers={"Retry-After": "30"},
            )
        return await call_next(request)


def _is_allowed(path: str) -> bool:
    return any(allowed in path for allowed in ALLOWED_PREFIXES)
