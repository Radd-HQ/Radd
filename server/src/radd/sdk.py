"""radd.sdk — the public, semver'd surface a plugin compiles against (§9).

This is the ONLY module a plugin should import from. Everything reachable here is
stable across a kernel major version (the loader refuses a plugin whose
`api_version` major mismatches — see `kernel.loader`). Everything else in `radd.*`
is internal and may change any release.

Two layers:
- **kernel** (eager): the plugin contract + contribution specs + registry
  `register_*` functions + `Base`/session helpers. No module dependencies.
- **data SDK** (lazy, via PEP 562): the permission-aware, acting-user-scoped read/
  write services (items, comments, projects, permissions, settings, events, access).
  Lazily resolved so importing `radd.sdk` doesn't drag in every feature module.

Everything in the data SDK enforces the acting user's permissions by construction
(§7.5): pass the acting `User`, get back only what they may see.
"""

import importlib
from typing import Any

# --- kernel surface (eager; safe, no module deps) ---
from radd.db import Base, TimestampMixin, get_session
from radd.kernel import (
    AutomationNodeSpec,
    KERNEL_API_VERSION,
    CapabilitySpec,
    CrudResourceSpec,
    EntityFieldSpec,
    EntitySpec,
    EntityRefSpec,
    EventTypeSpec,
    IntegrationSpec,
    McpToolSpec,
    NavItemSpec,
    PermissionSpec,
    PluginUiManifest,
    RaddPlugin,
    SettingSpec,
    SlqFieldSpec,
    TaskSpec,
    ViewTypeSpec,
    WidgetTypeSpec,
    register_capability,
    register_crud_resource,
    register_event_type,
    register_integration,
    register_permission,
    registries,
)
from radd.kernel import entities as entities  # kernel.entities.register_entity/build_model

API_VERSION = KERNEL_API_VERSION

# --- data SDK (lazy: name → (module, attribute)) ---
_LAZY: dict[str, tuple[str, str]] = {
    # items — permission-scoped reads/writes (pass the acting User)
    "get_item": ("radd.modules.items.service", "get_item"),
    "get_item_by_key": ("radd.modules.items.service", "get_item_by_key"),
    "list_items": ("radd.modules.items.service", "list_items"),
    "create_item": ("radd.modules.items.service", "create_item"),
    "update_item": ("radd.modules.items.service", "update_item"),
    # comments
    "list_comments": ("radd.modules.comments.service", "list_comments"),
    "create_comment": ("radd.modules.comments.service", "create_comment"),
    # projects
    "list_projects": ("radd.modules.projects.service", "list_projects"),
    "get_project": ("radd.modules.projects.service", "get_project"),
    # authorization
    "effective_permissions": ("radd.modules.auth.authz", "effective_permissions"),
    "require_permission": ("radd.modules.auth.authz", "require"),
    "Permission": ("radd.modules.auth.types", "Permission"),
    "CurrentUser": ("radd.modules.auth.deps", "CurrentUser"),
    # settings cascade
    "resolve_setting": ("radd.modules.settings.service", "resolve"),
    # events (produce/consume the outbox)
    "emit_event": ("radd.modules.events.service", "emit"),
    "read_events": ("radd.modules.events.service", "read_after"),
    # access grants (register a grantable ResourceSpec)
    "register_access_resource": ("radd.modules.access.registry", "register_resource"),
}


def __getattr__(name: str) -> Any:  # PEP 562 — lazy data-SDK resolution
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'radd.sdk' has no attribute {name!r}")
    module, attr = target
    return getattr(importlib.import_module(module), attr)


def __dir__() -> list[str]:
    return sorted([*globals().keys(), *_LAZY.keys()])
