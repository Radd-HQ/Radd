"""Shared helpers for MCP tool contributions (RADD-889).

`McpToolSpec` is kernel vocabulary, and its authors span feature modules and
external plugins alike — so the three fragments every paginated tool repeats
live here, below all of them. A per-module copy of the same clamp is how two
tools end up with different default page sizes.
"""

from collections.abc import Mapping
from typing import Any

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
