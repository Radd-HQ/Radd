from typing import Any

from pydantic import BaseModel


class CapabilityRead(BaseModel):
    key: str
    label: str
    category: str  # feature | auth | connector | storage | ai | infra
    enabled: bool
    detail: dict[str, Any] = {}
    #: The owning plugin's name — what the SPA links a status row through (RADD-1389).
    plugin: str = ""


class NavItemRead(BaseModel):
    """A plugin-contributed nav item (§8a). The SPA renders these alongside its
    builtin nav, gating each by `requires` against the user's /auth/me atoms — so a
    plugin's nav appears with no edit to the shell."""

    key: str
    label: str
    path: str
    icon: str = ""
    section: str = "main"  # main | settings
    group: str = ""
    requires_admin: bool = False
    requires_any_project: list[str] = []
    plugin: str = ""  # owning plugin, assigned by the registry
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
    # Entity types the remote serves live documents for (`PluginUiManifest.live_documents`): the host
    # holds those documents' own editor back while this remote is still loading.
    live_documents: list[str] = []


class TypeOptionRead(BaseModel):
    """A plugin-contributed pluggable type (a view type or dashboard widget type) — its stored key +
    the label the create-UI shows. The plugin's `view.type` / `dashboard.widget` slot renders it."""

    key: str
    label: str


class ViewListSurfaceRead(BaseModel):
    """A view type the host's LIST draws over the plugin's rows (RADD-1396, `ViewListSpec`)."""

    rows_path: str = ""
    columns: list[str] = []
    refresh_seconds: int = 0


class ViewTypeOptionRead(TypeOptionRead):
    """A plugin-contributed view type: drawn by its `view.type` slot, or — with `list_surface` —
    by the host's list over the plugin's rows; `sidebar_section` lists its views in a section of
    their own with live counts (RADD-1396)."""

    icon: str = ""
    list_surface: ViewListSurfaceRead | None = None
    sidebar_section: str = ""


class WidgetTypeOptionRead(TypeOptionRead):
    """A plugin-contributed dashboard widget type. A `personal` one belongs on My Work only —
    it shows the viewer's own work (RADD-1393)."""

    personal: bool = False


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
    view_types: list[ViewTypeOptionRead] = []
    widget_types: list[WidgetTypeOptionRead] = []
