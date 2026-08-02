from typing import Any

from pydantic import BaseModel


class CapabilityRead(BaseModel):
    key: str
    label: str
    category: str  # feature | auth | connector | storage | ai | infra
    enabled: bool
    detail: dict[str, Any] = {}


class NavItemRead(BaseModel):
    """A plugin-contributed nav item (§8a). The SPA renders these alongside its
    builtin nav, gating each by `requires` against the user's /auth/me atoms — so a
    plugin's nav appears with no edit to the shell."""

    key: str
    label: str
    path: str
    icon: str = ""
    section: str = "main"  # main | settings
    requires: list[str] = []  # permission atoms that must ALL be held
    capability: str = ""  # hide unless this capability is enabled
    order: int = 100


class PluginRemoteRead(BaseModel):
    """A plugin UI remote the host runtime loader imports (spec 94, module federation). Present for
    each ENABLED plugin that ships a federated UI bundle (`ui.remote`). Disabling a plugin drops it
    from this list, so the host unmounts its UI live."""

    name: str  # the stable plugin enable-key
    remote_entry: str  # URL of the remote's ESM bundle to import()
    ui_api_version: str  # the SDK major it targets; the host version-gates on it


class TypeOptionRead(BaseModel):
    """A plugin-contributed pluggable type (a view type or dashboard widget type) — its stored key +
    the label the create-UI shows. The plugin's `view.type` / `dashboard.widget` slot renders it."""

    key: str
    label: str


class CapabilitiesRead(BaseModel):
    """The backend-assembled UI manifest the SPA renders nav/status from (§8a) —
    the inversion of the hardcoded SETTINGS_NAV / sidebar arrays (chokepoint 3)."""

    capabilities: list[CapabilityRead]
    nav: list[NavItemRead] = []
    # The ids of every currently-ENABLED plugin — lets the SPA hide UI for a
    # disabled optional plugin (e.g. the issue view's Participants/Approvals/CSAT
    # sections) without hardcoding which features exist (spec 93 / A7).
    plugins: list[str] = []
    # Federated UI remotes to load at runtime (spec 94) — one per enabled plugin with a UI bundle.
    remotes: list[PluginRemoteRead] = []
    # Plugin-contributed pluggable types (spec 94): the create-view / add-widget dropdowns list these.
    view_types: list[TypeOptionRead] = []
    widget_types: list[TypeOptionRead] = []
