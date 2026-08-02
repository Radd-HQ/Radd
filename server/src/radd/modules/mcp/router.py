"""POST {api_prefix}/mcp — the embedded MCP server endpoint (spec 45).

Streamable-HTTP transport, JSON-only: one JSON-RPC 2.0 message per POST body
(no SSE streaming, no sessions beyond auth). Module routers are mounted under
`settings.api_prefix`, so the endpoint lives at **POST /api/v1/mcp** — point an
MCP client there with `Authorization: Bearer radd_pat_…`.

Layering:
- HTTP level: disabled instance -> 403; missing/invalid credentials -> 401
  (PAT is the primary path; a session cookie also works via the auth deps).
- Protocol level: malformed body -> -32700/-32600, unknown method -> -32601,
  bad tools/call params or unknown tool -> -32602 (JSON-RPC error envelopes).
- Tool level: domain errors (NotFound/Forbidden/Conflict/Unauthorized/…
  RaddError) -> `isError: true` results with the message text — NEVER
  JSON-RPC protocol errors. The session is rolled back first so a half-applied
  mutation is not committed by the request teardown.
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from radd import __version__
from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError, RaddError, UnauthorizedError
from radd.modules.auth.deps import OptionalUser
from radd.modules.auth.models import User

from . import tools
from .protocol import JsonRpcError, JsonRpcRequest, error_envelope, parse_request, result_envelope
from .types import (
    HTTP_ACCEPTED,
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_NAME,
    JsonRpcErrorCode,
    McpContentType,
    McpMethod,
)

router = APIRouter(prefix="/mcp", tags=["mcp"])

Session = Annotated[AsyncSession, Depends(get_session)]

# Argument-shape failures inside a tool run (bad enum value, pydantic validation —
# a ValueError subclass) read as tool errors too: the agent gets an actionable
# message instead of a protocol fault.
_TOOL_ERROR_TYPES = (RaddError, ValueError)


def _initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": MCP_SERVER_NAME, "version": __version__},
    }


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
    except _TOOL_ERROR_TYPES as exc:
        # Discard any partial flush before the request teardown commits.
        await session.rollback()
        return {
            "content": [{"type": McpContentType.TEXT.value, "text": str(exc)}],
            "isError": True,
        }
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
            return {"tools": await tools.live_catalog(session)}
        case McpMethod.TOOLS_CALL:
            return await _tools_call(session, user, message.params)
        case _:
            raise JsonRpcError(
                JsonRpcErrorCode.METHOD_NOT_FOUND, f"method '{message.method}' not supported"
            )


@router.post("")
async def mcp_endpoint(request: Request, session: Session, user: OptionalUser) -> Response:
    """The MCP Streamable-HTTP endpoint (see module docstring for semantics)."""
    if not settings.mcp_enabled:
        raise ForbiddenError("MCP server is disabled (RADD_MCP_ENABLED=false)")
    if user is None:
        raise UnauthorizedError(
            "MCP requires a personal access token: Authorization: Bearer radd_pat_…"
        )
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
