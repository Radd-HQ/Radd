import logging

from fastapi import APIRouter, Request, Response, status

from radd.modules.auth.deps import OptionalUser

from . import limiter
from .schemas import ClientErrorReport

router = APIRouter(tags=["diagnostics"])
logger = logging.getLogger("radd.client_error")


@router.post("/client-errors", status_code=status.HTTP_204_NO_CONTENT)
async def report_client_error(
    report: ClientErrorReport, request: Request, user: OptionalUser
) -> Response:
    """One browser error becomes one log line. Open before sign-in (the login page
    can crash too), so it is bounded in size by the schema and in rate per address
    here; a report over the allowance is dropped with a 429 and never logged."""
    address = getattr(request.state, "client_ip", None) or "unknown"
    if not limiter.admit(address):
        return Response(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    logger.error(
        "client error: %s",
        report.message,
        extra={
            "client_error": {
                "message": report.message,
                "stack": report.stack,
                "route": report.route,
                "source": report.source,
                "plugin": report.plugin,
                "build": report.build,
                "user_id": str(user.id) if user else None,
                "address": address,
                "user_agent": request.headers.get("user-agent", "")[:300],
            }
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
