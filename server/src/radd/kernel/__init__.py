"""The Radd kernel — the generic machinery every feature (plugin) builds on.

Kernel = config/loader/lifecycle, the entity & event-type registries, access
control + the permission-aware data SDK, the settings platform + /capabilities,
the contribution registries, and the [primitive] socket seams. Never disabled.
Concrete features are plugins (docs/plugin-platform.md §1).

This package holds the *machinery*; the generic mechanism modules (events, access,
auth-core, settings) remain in `radd.modules.*` for import stability but are
governed by this contract.
"""

from .loader import PluginLoadError, import_models, load_plugins
from .plugin import KERNEL_API_VERSION, RaddPlugin
from .registry import (
    KernelRegistries,
    register_capability,
    register_crud_resource,
    register_event_type,
    register_integration,
    register_permission,
    registries,
)
from .specs import (
    CapabilitySpec,
    ConsumerSpec,
    CrudResourceSpec,
    EntityFieldSpec,
    EntitySpec,
    EventTypeSpec,
    IntegrationSpec,
    McpToolSpec,
    NavItemSpec,
    PermissionSpec,
    PluginUiManifest,
    SettingSectionSpec,
    SlqFieldContext,
    SlqFieldSpec,
    TaskSpec,
    ViewTypeSpec,
    WidgetTypeSpec,
)

__all__ = [
    "RaddPlugin",
    "KERNEL_API_VERSION",
    "PluginLoadError",
    "load_plugins",
    "import_models",
    "registries",
    "KernelRegistries",
    "register_event_type",
    "register_permission",
    "register_crud_resource",
    "register_capability",
    "register_integration",
    "EventTypeSpec",
    "CapabilitySpec",
    "PermissionSpec",
    "SlqFieldContext",
    "SlqFieldSpec",
    "ViewTypeSpec",
    "WidgetTypeSpec",
    "CrudResourceSpec",
    "EntitySpec",
    "EntityFieldSpec",
    "TaskSpec",
    "ConsumerSpec",
    "IntegrationSpec",
    "McpToolSpec",
    "NavItemSpec",
    "PluginUiManifest",
    "SettingSectionSpec",
]
