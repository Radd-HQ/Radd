"""MCP tool dispatch (spec 45) — one registry, one path (RADD-889).

Every tool in the catalog is a kernel `McpToolSpec` contributed by its OWNER
module (the spec-45/114 builtins moved out of this file to items, timelogging,
releases, pages, projects, auth and search), so dispatch is a single live
registry lookup: a disabled plugin's tools stop dispatching the moment they
leave the catalog. Handlers resolve the PAT-authed actor's request through the
ordinary service/authz seams — an agent can do exactly what its principal may
do, nothing more. Domain failures (RaddError subclasses) bubble up for the
router to shape into `isError: true` results; the catalog lives in catalog.py.
"""

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.projects import service as projects_service

from .catalog import build_catalog, live_catalog, pages_available  # re-export: the tool surface

__all__ = ["UnknownToolError", "build_catalog", "call_tool", "pages_available", "live_catalog"]


class UnknownToolError(Exception):
    """tools/call named a tool outside the catalog -> JSON-RPC INVALID_PARAMS
    (deliberately NOT a RaddError: it must not become an isError tool result)."""

    def __init__(self, name: str):
        super().__init__(f"unknown tool '{name}'")


async def _call_registry_tool(
    session: AsyncSession, actor: User, spec: Any, arguments: Mapping[str, Any]
) -> Any:
    """A registered tool inherits ENFORCEMENT, not just catalog filtering
    (RADD-640): for a kernel-enforced spec the declared atom is required before
    the handler runs, so a plugin cannot accidentally expose an unfiltered tool.
    When the spec names a project parameter and the call carries it, the atom is
    required on THAT project. The migrated builtins opt out
    (`kernel_enforced=False`): their handlers carry the pre-RADD-889 enforcement
    at the service seam, where the row-level rules live."""
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
    """Dispatch one tools/call through the kernel registry — a live lookup, so a
    disabled plugin's (or module's) tools stop dispatching the moment they leave
    the catalog. Raises UnknownToolError for names not registered; RaddError
    subclasses bubble up for the router to shape into `isError: true` results."""
    from radd.kernel import registries  # deferred: keep the kernel import lazy

    spec = registries.mcp_tools.get(name)
    if spec is None:
        raise UnknownToolError(name)
    return await _call_registry_tool(session, actor, spec, arguments)
