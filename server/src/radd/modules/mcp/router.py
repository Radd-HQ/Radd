"""{api_prefix}/mcp — the embedded MCP server (spec 45), Streamable HTTP: one JSON-RPC 2.0
message per POST (JSON only), plus the GET event stream that carries `tools/list_changed`
(RADD-740). Authenticate with `Bearer radd_pat_…` (a session cookie also works).

- HTTP: disabled → 403; no credentials → 401.
- Protocol: bad body -32700/-32600, unknown method -32601, bad params / unknown tool /
  arguments the advertised schema rejects -32602 (violations in `data`).
- Tool: RaddError/ValueError → `isError: true` after a rollback (so teardown cannot commit
  a half-applied mutation); anything else rolls back, logs and answers -32603 — never
  HTTP 500 (RADD-905).
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from radd import __version__
from radd.config import settings
from radd.db import SessionLocal, commit_before_streaming, get_session
from radd.exceptions import ForbiddenError, RaddError, UnauthorizedError
from radd.kernel.mcptools import InvalidArgumentsError
from radd.modules.auth.deps import OptionalUser
from radd.modules.auth.models import User

from . import catalog, tools
from .protocol import JsonRpcError, JsonRpcRequest, error_envelope, parse_request, result_envelope
from .types import (
    HTTP_ACCEPTED,
    SSE_HEADERS,
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_NAME,
    JsonRpcErrorCode,
    McpContentType,
    McpMethod,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

Session = Annotated[AsyncSession, Depends(get_session)]

# Argument-shape failures inside a tool run (bad enum value, pydantic validation —
# a ValueError subclass) read as tool errors too: the agent gets an actionable
# message instead of a protocol fault.
_TOOL_ERROR_TYPES = (RaddError, ValueError)


def _require_mcp_user(user: User | None) -> User:
    if not settings.mcp_enabled:
        raise ForbiddenError("MCP server is disabled (RADD_MCP_ENABLED=false)")
    if user is None:
        raise UnauthorizedError(
            "MCP requires a personal access token: Authorization: Bearer radd_pat_…"
        )
    return user


def _initialize_result() -> dict[str, Any]:
    """`listChanged` is true because GET /mcp is the channel it travels (RADD-740)."""
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": MCP_SERVER_NAME, "version": __version__},
    }


async def _catalog_change_stream(user: User) -> AsyncIterator[str]:
    """Emit `notifications/tools/list_changed` when this principal's catalog fingerprint
    changes. Polled, not event-driven: a deploy, a plugin mounting and the caller's own
    scopes all move it, and only the last is an event this process sees. Each tick opens
    its OWN session: the stream outlives the request, and holding one pins a connection per
    agent."""
    yield ": connected\n\n"  # flush headers; also what makes this route testable
    last: str | None = None
    idle = 0.0
    while True:
        async with SessionLocal() as session:
            current = await catalog.catalog_fingerprint(session, user)
        if last is None:
            last = current
        elif current != last:
            last = current
            idle = 0.0
            yield f"data: {json.dumps({'jsonrpc': '2.0', 'method': McpMethod.TOOLS_LIST_CHANGED.value})}\n\n"
        if idle >= settings.mcp_stream_keepalive_seconds:
            idle = 0.0
            yield ": keepalive\n\n"  # a comment frame; proxies drop idle streams
        await asyncio.sleep(settings.mcp_catalog_poll_seconds)
        idle += settings.mcp_catalog_poll_seconds


@router.get("")
async def mcp_stream(user: OptionalUser, session: Session) -> Response:
    """The server→client half of Streamable HTTP (RADD-740)."""
    user = _require_mcp_user(user)
    # The auth read opened a transaction on the request session, and teardown
    # won't commit it until the stream ENDS — hours later (RADD-845).
    await commit_before_streaming(session)
    return StreamingResponse(
        _catalog_change_stream(user), media_type="text/event-stream", headers=SSE_HEADERS
    )


async def _tools_call(session: AsyncSession, user: User, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not name:
        raise JsonRpcError(JsonRpcErrorCode.INVALID_PARAMS, "params.name must be a tool name")
    if not isinstance(arguments, dict):
        raise JsonRpcError(JsonRpcErrorCode.INVALID_PARAMS, "params.arguments must be an object")
    try:
        result = await tools.call_tool(session, user, name, arguments)
    except tools.UnknownToolError as exc:
        raise JsonRpcError(JsonRpcErrorCode.INVALID_PARAMS, str(exc)) from None
    except InvalidArgumentsError as exc:
        raise JsonRpcError(JsonRpcErrorCode.INVALID_PARAMS, str(exc), data=exc.errors) from None
    except _TOOL_ERROR_TYPES as exc:
        # Discard any partial flush before the request teardown commits.
        await session.rollback()
        return {
            "content": [{"type": McpContentType.TEXT.value, "text": str(exc)}],
            "isError": True,
        }
    except Exception as exc:
        # RADD-905: a handler bug is rolled back and answered inside the protocol.
        await session.rollback()
        logger.exception("mcp tool %r failed", name)
        raise JsonRpcError(
            JsonRpcErrorCode.INTERNAL_ERROR, f"tool '{name}' failed: {type(exc).__name__}: {exc}"
        ) from None
    return {
        "content": [
            {
                "type": McpContentType.TEXT.value,
                "text": json.dumps(result, ensure_ascii=False, default=str),
            }
        ],
        "isError": False,
    }


async def handle_request(
    session: AsyncSession, user: User, message: JsonRpcRequest
) -> dict[str, Any]:
    """Route one non-notification request to its result (raises JsonRpcError)."""
    match message.method:
        case McpMethod.INITIALIZE:
            return _initialize_result()
        case McpMethod.PING:
            return {}
        case McpMethod.TOOLS_LIST:
            return {"tools": await tools.live_catalog(session, user)}
        case McpMethod.TOOLS_CALL:
            return await _tools_call(session, user, message.params)
        case _:
            raise JsonRpcError(
                JsonRpcErrorCode.METHOD_NOT_FOUND, f"method '{message.method}' not supported"
            )


@router.post("")
async def mcp_endpoint(request: Request, session: Session, user: OptionalUser) -> Response:
    """The MCP Streamable-HTTP endpoint (see module docstring for semantics)."""
    user = _require_mcp_user(user)
    try:
        message = parse_request(await request.body())
    except JsonRpcError as exc:
        return JSONResponse(error_envelope(exc.id, exc.code, str(exc), exc.data))
    if message.is_notification:
        # notifications/initialized and any other notification: acknowledge, no body.
        return Response(status_code=HTTP_ACCEPTED)
    try:
        result = await handle_request(session, user, message)
    except JsonRpcError as exc:
        return JSONResponse(error_envelope(message.id, exc.code, str(exc), exc.data))
    return JSONResponse(result_envelope(message.id, result))
