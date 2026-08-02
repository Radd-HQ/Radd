from enum import StrEnum


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


class PluginEntity(StrEnum):
    PLUGIN = "plugin"
