"""The plugin contract — `RaddPlugin`, the manifest of contributions.

Evolves the pre-kernel `RaddModule` (routers + lifecycle hooks) into a manifest
of *declarations* the loader aggregates into kernel registries
(docs/plugin-platform.md §4). All 49 builtin plugins construct `RaddPlugin`
directly; the migration is finished, so the `RaddModule` alias is gone. The
minimal `name=`/`description=`/`routers=` constructor still builds a valid
plugin with `core: true` and empty new fields (§11.1).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request, Response

from .specs import (
    CapabilitySpec,
    ConsumerSpec,
    CrudResourceSpec,
    EntitySpec,
    EventTypeSpec,
    IntegrationSpec,
    McpToolSpec,
    PermissionSpec,
    PluginUiManifest,
    SettingSectionSpec,
    SlqFieldSpec,
    TaskSpec,
    ViewTypeSpec,
    WidgetTypeSpec,
)

ExceptionHandler = Callable[[Request, Any], Response | Awaitable[Response]]
OpenApiAugmentor = Callable[[dict[str, Any]], None]
StartupHook = Callable[[], Awaitable[None]]

# The kernel SDK version plugins target (§9). Loader refuses an incompatible major.
KERNEL_API_VERSION = "1.0"


@dataclass(frozen=True)
class RaddPlugin:
    """A feature, declared. Identity + lifecycle + a manifest of contributions.

    `name` doubles as `id` when `id` is unset, so the minimal
    `RaddPlugin(name=…, description=…, routers=…)` form still constructs.
    """

    name: str
    description: str = ""

    # identity & lifecycle
    id: str = ""  # stable, e.g. "radd.slas"; defaults to `name`
    version: str = "0.0.0"
    api_version: str = KERNEL_API_VERSION
    core: bool = True  # reclassified builtins are core (non-disableable); externals set False
    depends_on: tuple[str, ...] = ()  # other plugin names that must load first
    # Per-plugin dependencies (§14): the Python distributions + npm packages this
    # plugin needs. Builtins map to optional-dependency extras (radd[ldap,ai,…]); the
    # install step resolves them. Declarative here so the manifest is the single
    # source of truth for what a plugin pulls in.
    python_deps: tuple[str, ...] = ()
    js_deps: tuple[str, ...] = ()

    # --- contributions (each → a kernel registry) ---
    routers: tuple[APIRouter, ...] = ()
    entities: tuple[EntitySpec, ...] = ()
    event_types: tuple[EventTypeSpec, ...] = ()
    consumers: tuple[ConsumerSpec, ...] = ()
    automation_actions: tuple[Any, ...] = ()
    automation_conditions: tuple[Any, ...] = ()
    tasks: tuple[TaskSpec, ...] = ()
    settings_keys: tuple[Any, ...] = ()
    settings_sections: tuple[SettingSectionSpec, ...] = ()
    permissions: tuple[PermissionSpec, ...] = ()
    crud_resources: tuple[CrudResourceSpec, ...] = ()
    access_resources: tuple[Any, ...] = ()
    capabilities: tuple[CapabilitySpec, ...] = ()
    slq_fields: tuple[SlqFieldSpec, ...] = ()  # custom SLQ query fields (e.g. `note ~ "x"`)
    view_types: tuple[ViewTypeSpec, ...] = ()  # custom saved-view types
    widget_types: tuple[WidgetTypeSpec, ...] = ()  # custom dashboard widget types
    mcp_tools: tuple[McpToolSpec, ...] = ()  # MCP tools (RADD-640; filtered + enforced by the kernel)
    integrations: tuple[IntegrationSpec, ...] = ()
    ui: PluginUiManifest | None = None

    # kept from the pre-kernel module contract
    exception_handlers: tuple[tuple[type[Exception], ExceptionHandler], ...] = ()
    openapi_augmentors: tuple[OpenApiAugmentor, ...] = ()
    on_startup: tuple[StartupHook, ...] = ()
    on_shutdown: tuple[StartupHook, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", self.name)

