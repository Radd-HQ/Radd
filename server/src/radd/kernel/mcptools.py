"""Shared helpers for MCP tool contributions (RADD-889).

`McpToolSpec` is kernel vocabulary, and its authors span feature modules and
external plugins alike — so the three fragments every paginated tool repeats
live here, below all of them. A per-module copy of the same clamp is how two
tools end up with different default page sizes.
"""

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

# tools/call result shaping (spec 45) — one page budget for every list tool.
SEARCH_LIMIT_DEFAULT = 25
SEARCH_LIMIT_MAX = 100


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
    """tools/call arguments do not match the tool's declared input schema
    (RADD-1106/905) -> JSON-RPC INVALID_PARAMS.

    Deliberately NOT a RaddError: an argument-shape failure is a protocol
    fault, not a tool result. `errors` carries every violation as
    `{path, message}` so an agent can fix them all in one round trip.
    """

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
    """Refuse arguments the tool's advertised schema does not admit — a missing
    required property, an unknown one (every tool schema is CLOSED), a mistyped
    value. Before this, a handler's own KeyError/TypeError escaped as an HTTP
    500 and an unknown property was silently ignored (`list_worklogs
    {"key": …}` answered with every worklog). Raises InvalidArgumentsError
    carrying ALL violations."""
    validator = Draft202012Validator(
        dict(schema), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    violations = sorted(
        (_violation(error) for error in validator.iter_errors(dict(arguments))),
        key=lambda violation: (violation["path"], violation["message"]),
    )
    if violations:
        raise InvalidArgumentsError(tool, violations)
