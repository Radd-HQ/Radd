from enum import StrEnum


class PluginOrigin(StrEnum):
    """Where a plugin ships from (RADD-898): the main image + migration chain
    (`bootstrap`) or the installable set (`installable`) — previously bare
    strings compared across service.py."""

    BOOTSTRAP = "bootstrap"
    INSTALLABLE = "installable"


class PluginState(StrEnum):
    """The lifecycle states (docs/plugin-platform.md §10). Core plugins are always
    ENABLED and locked. Non-core: DISCOVERED → INSTALLED → ENABLED ⇄ DISABLED.
    These are desired states, applied by each process at runtime. Forgetting preserves data."""

    DISCOVERED = "discovered"  # known to the manager, not installed
    INSTALLED = "installed"  # registered, not requested active
    ENABLED = "enabled"  # requested active
    DISABLED = "disabled"  # requested inactive
    ERRORED = "errored"  # quarantined: load/startup threw (boot survives)


class RuntimeState(StrEnum):
    """How the running processes stand against a plugin's desired state (RADD-1341)."""

    APPLYING = "applying"  # some live process has not applied it yet
    ERROR = "error"  # a live process failed to apply it; retried with backoff
    ENABLED = "enabled"
    DISABLED = "disabled"


class PluginEvent(StrEnum):
    PACKAGE_UPLOADED = "plugin.package_uploaded"
    PACKAGE_REMOVED = "plugin.package_removed"
    INSTALLED = "plugin.installed"
    ENABLED = "plugin.enabled"
    DISABLED = "plugin.disabled"
    UNINSTALLED = "plugin.uninstalled"
    # Spec 123: a contribution switched on/off instance-wide (RADD-1168 — the
    # write used to leave no event).
    CONTRIBUTIONS_CHANGED = "plugin.contributions_changed"


class PluginEntity(StrEnum):
    PLUGIN = "plugin"
