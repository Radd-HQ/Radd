from enum import StrEnum


class PluginOrigin(StrEnum):
    """Where a plugin ships from (RADD-898): the main image + migration chain
    (`bootstrap`) or the installable set (`installable`) — previously bare
    strings compared across service.py."""

    BOOTSTRAP = "bootstrap"
    INSTALLABLE = "installable"


class PluginState(StrEnum):
    """The lifecycle states (docs/plugin-platform.md §10). Core plugins are always
    ENABLED and locked. Non-core: DISCOVERED → INSTALLED (migrations up) → ENABLED
    ⇄ DISABLED → UNINSTALLED (migrations down)."""

    DISCOVERED = "discovered"  # known to the manager, not installed
    INSTALLED = "installed"  # tables migrated, not active
    ENABLED = "enabled"  # active (routers mounted, tasks running, nav shown)
    DISABLED = "disabled"  # installed but inactive
    ERRORED = "errored"  # quarantined: load/startup threw (boot survives)


class PluginEvent(StrEnum):
    INSTALLED = "plugin.installed"
    ENABLED = "plugin.enabled"
    DISABLED = "plugin.disabled"
    UNINSTALLED = "plugin.uninstalled"
    # Spec 123: a contribution switched on/off instance-wide (RADD-1168 — the
    # write used to leave no event).
    CONTRIBUTIONS_CHANGED = "plugin.contributions_changed"


class PluginEntity(StrEnum):
    PLUGIN = "plugin"
