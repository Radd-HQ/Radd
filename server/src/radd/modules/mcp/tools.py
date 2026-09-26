"""MCP tool dispatch (spec 45): one live registry lookup (RADD-889), so a disabled plugin's
tools stop dispatching when they leave the catalog. Handlers run through the ordinary
service/authz seams as the PAT's principal; domain errors bubble to the router."""

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import registries
from radd.kernel.mcptools import validate_arguments
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.projects import service as projects_service

from .catalog import (  # re-export: the tool surface
    build_catalog,
    live_catalog,
    live_schema,
)

__all__ = ["UnknownToolError", "build_catalog", "call_tool", "live_catalog"]


class UnknownToolError(Exception):
    """tools/call named a tool outside the catalog -> JSON-RPC INVALID_PARAMS
    (deliberately NOT a RaddError: it must not become an isError tool result)."""

    def __init__(self, name: str):
        super().__init__(f"unknown tool '{name}'")


async def _call_registry_tool(
    session: AsyncSession, actor: User, spec: Any, arguments: Mapping[str, Any]
) -> Any:
    """A kernel-enforced spec's atom is REQUIRED before the handler runs (RADD-640) — on the
    `project_param` project when the call names one — so a plugin cannot expose an
    unfiltered tool. The builtins opt out: their service seams enforce row-level rules."""
    if spec.kernel_enforced:
        project = None
        if spec.project_param and arguments.get(spec.project_param):
            project = await projects_service.get_by_key(
                session, str(arguments[spec.project_param])
            )
        if spec.permission:
            await authz.require(session, actor, cast(Permission, spec.permission), project=project)
    return await spec.handler(session, actor, arguments)


async def call_tool(
    session: AsyncSession, actor: User, name: str, arguments: Mapping[str, Any]
) -> Any:
    """Dispatch one tools/call. Raises UnknownToolError for an unregistered name and
    InvalidArgumentsError (RADD-1106) for arguments the ADVERTISED schema — the one
    tools/list renders — does not admit, so a typo'd property is refused, not ignored."""
    spec = registries.mcp_tools.get(name)
    if spec is None:
        raise UnknownToolError(name)
    validate_arguments(name, await live_schema(session, spec), arguments)
    return await _call_registry_tool(session, actor, spec, arguments)
