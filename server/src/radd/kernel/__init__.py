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
from .hosts import EntityHost, entity_host, set_entity_host
from . import changes
from .specs import (
    OUTPUT_NAME_RE,
    AutomationNodeSpec,
    CapabilitySpec,
    CascadeSpec,
    CrudResourceSpec,
    EntityFieldSpec,
    EntitySpec,
    EntityRefSpec,
    EventTypeSpec,
    GrantScopeSpec,
    ProjectRelationSpec,
    RowGuardSpec,
    IntegrationSpec,
    McpToolSpec,
    NavFactSpec,
    NavItemSpec,
    OutputField,
    OutputKind,
    PageExtensionSpec,
    PermissionSpec,
    PluginUiManifest,
    ProjectPurgeSpec,
    SettingSpec,
    SlqFieldContext,
    SlqFieldSpec,
    TaskSpec,
    valid_output_name,
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
    "changes",
    "KernelRegistries",
    "register_event_type",
    "register_permission",
    "register_crud_resource",
    "register_capability",
    "register_integration",
    "EntityRefSpec",
    "EventTypeSpec",
    "CapabilitySpec",
    "CascadeSpec",
    "PermissionSpec",
    "SlqFieldContext",
    "SlqFieldSpec",
    "ViewTypeSpec",
    "WidgetTypeSpec",
    "CrudResourceSpec",
    "EntitySpec",
    "EntityFieldSpec",
    "TaskSpec",
    "IntegrationSpec",
    "AutomationNodeSpec",
    "OutputField",
    "OutputKind",
    "OUTPUT_NAME_RE",
    "valid_output_name",
    "McpToolSpec",
    "PageExtensionSpec",
    "NavItemSpec",
    "NavFactSpec",
    "GrantScopeSpec",
    "ProjectRelationSpec",
    "RowGuardSpec",
    "ProjectPurgeSpec",
    "PluginUiManifest",
    "SettingSpec",
    "EntityHost",
    "entity_host",
    "set_entity_host",
]
