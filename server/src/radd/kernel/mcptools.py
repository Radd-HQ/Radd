"""Shared helpers for MCP tool contributions (RADD-889) — one copy of the paging clamp, so
two tools cannot end up with different default page sizes."""

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

# tools/call result shaping (spec 45) — one page budget for every list tool.
SEARCH_LIMIT_DEFAULT = 25
SEARCH_LIMIT_MAX = 100


class ToolContentType(StrEnum):
    """tools/call result content block types: a handler's JSON is wrapped as TEXT by the
    dispatcher; IMAGE and RESOURCE are what a `ToolContent` carries through untouched."""

    TEXT = "text"
    IMAGE = "image"
    RESOURCE = "resource"


@dataclass(frozen=True)
class ToolContent:
    """A handler's result as MCP content blocks instead of a JSON document — for bytes
    (an image the agent can look at, a file as an embedded resource) that JSON cannot
    carry. The dispatcher passes `blocks` through as the result's `content`."""

    blocks: tuple[dict[str, Any], ...]

    @staticmethod
    def text_block(text: str) -> dict[str, Any]:
        return {"type": ToolContentType.TEXT.value, "text": text}

    @staticmethod
    def image_block(data: bytes, mime_type: str) -> dict[str, Any]:
        return {
            "type": ToolContentType.IMAGE.value,
            "data": base64.b64encode(data).decode("ascii"),
            "mimeType": mime_type,
        }

    @staticmethod
    def resource_block(uri: str, mime_type: str, data: bytes) -> dict[str, Any]:
        return {
            "type": ToolContentType.RESOURCE.value,
            "resource": {
                "uri": uri,
                "mimeType": mime_type,
                "blob": base64.b64encode(data).decode("ascii"),
            },
        }


def limit_arg(args: Mapping[str, Any]) -> int:
    """The clamped `limit` argument (the default when absent)."""
    raw = args.get("limit", SEARCH_LIMIT_DEFAULT)
    return max(1, min(int(raw), SEARCH_LIMIT_MAX))


def limit_property() -> dict[str, Any]:
    """The `limit` input-schema property those tools share."""
    return {
        "type": "integer",
        "minimum": 1,
        "maximum": SEARCH_LIMIT_MAX,
        "default": SEARCH_LIMIT_DEFAULT,
    }


def object_schema(
    properties: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    """A CLOSED JSON-Schema object — every tool schema is one, so agents get
    typo safety instead of silently ignored arguments."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


class InvalidArgumentsError(Exception):
    """tools/call arguments the tool's schema rejects (RADD-1106) -> JSON-RPC INVALID_PARAMS.
    Not a RaddError: a protocol fault, not a tool result. `errors` carries EVERY violation
    as `{path, message}`, so an agent fixes them in one round trip."""

    def __init__(self, tool: str, errors: list[dict[str, str]]):
        self.tool = tool
        self.errors = errors
        detail = "; ".join(
            f"{error['path']}: {error['message']}" if error["path"] else error["message"]
            for error in errors
        )
        super().__init__(f"invalid arguments for tool '{tool}': {detail}")


def _violation(error: ValidationError) -> dict[str, str]:
    return {
        "path": ".".join(str(segment) for segment in error.absolute_path),
        "message": error.message,
    }


def validate_arguments(tool: str, schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> None:
    """Refuse arguments the advertised schema does not admit (missing, unknown — every schema
    is CLOSED — or mistyped); raises InvalidArgumentsError carrying ALL violations."""
    validator = Draft202012Validator(
        dict(schema), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    violations = sorted(
        (_violation(error) for error in validator.iter_errors(dict(arguments))),
        key=lambda violation: (violation["path"], violation["message"]),
    )
    if violations:
        raise InvalidArgumentsError(tool, violations)
