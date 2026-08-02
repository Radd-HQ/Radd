"""Pure JSON-RPC 2.0 envelope handling (spec 45) — no FastAPI, no DB.

Parses a Streamable-HTTP POST body into a `JsonRpcRequest` and builds
result/error envelopes. Protocol-level failures raise `JsonRpcError`, which the
router turns into a JSON-RPC error envelope; domain/tool failures never reach
this layer (they become `isError: true` tool results).

Batch arrays are rejected: JSON-RPC batching was removed in MCP revision
2025-06-18, the version whose semantics we implement.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from .types import JSONRPC_VERSION, JsonRpcErrorCode

# JSON-RPC ids are strings or integers; None appears only in error envelopes
# for requests whose id could not be read (parse errors).
RequestId = int | str | None


@dataclass(frozen=True)
class JsonRpcRequest:
    """One parsed request. `is_notification` = the `id` member was absent."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: RequestId = None
    is_notification: bool = False


class JsonRpcError(Exception):
    """A protocol-level failure -> one JSON-RPC error envelope."""

    def __init__(
        self,
        code: JsonRpcErrorCode,
        message: str,
        *,
        id: RequestId = None,
        data: Any = None,
    ):
        self.code = code
        self.id = id
        self.data = data
        super().__init__(message)


def parse_request(body: bytes | str) -> JsonRpcRequest:
    """Parse a raw POST body into a request. Raises JsonRpcError with
    PARSE_ERROR (-32700) for invalid JSON, INVALID_REQUEST (-32600) for a
    well-formed body that is not a valid single JSON-RPC request object."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JsonRpcError(JsonRpcErrorCode.PARSE_ERROR, f"invalid JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise JsonRpcError(
            JsonRpcErrorCode.INVALID_REQUEST,
            "expected a single JSON-RPC request object (batching is not supported)",
        )
    request_id = payload.get("id")
    if not isinstance(request_id, int | str | None):
        raise JsonRpcError(JsonRpcErrorCode.INVALID_REQUEST, "id must be a string or integer")
    if payload.get("jsonrpc") != JSONRPC_VERSION:
        raise JsonRpcError(
            JsonRpcErrorCode.INVALID_REQUEST, "jsonrpc must be '2.0'", id=request_id
        )
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise JsonRpcError(
            JsonRpcErrorCode.INVALID_REQUEST, "method must be a non-empty string", id=request_id
        )
    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise JsonRpcError(
            JsonRpcErrorCode.INVALID_REQUEST, "params must be an object", id=request_id
        )
    return JsonRpcRequest(
        method=method, params=params, id=request_id, is_notification="id" not in payload
    )


def result_envelope(request_id: RequestId, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def error_envelope(
    request_id: RequestId, code: JsonRpcErrorCode, message: str, data: Any = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": int(code), "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}
