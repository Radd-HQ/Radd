"""pluginmgr — the plugin manager (lifecycle + admin API, docs/plugin-platform.md §10).

A core plugin that owns the `installed_plugins` table and the install/enable/disable/
uninstall state machine over non-core plugins. Enable/disable flip the state (persisted)
and hot-mount/unmount routers in the running app; `create_app` also resolves the enabled
set at boot. Core plugins are locked (always enabled). This is what makes "runtime toggle
in the admin UI" real.
"""

from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from .types import PluginEvent

plugin = RaddPlugin(
    name="pluginmgr",
    description="Plugin lifecycle manager: install/enable/disable/uninstall + installed_plugins.",
    depends_on=("auth", "events"),
    routers=(router,),
    # Admin lifecycle events — registered for audit/webhooks but NOT automation
    # triggers (trigger=False), so they don't clutter the rule builder.
    event_types=(
        EventTypeSpec(PluginEvent.INSTALLED, "Plugin installed", "Plugins", trigger=False),
        EventTypeSpec(PluginEvent.ENABLED, "Plugin enabled", "Plugins", trigger=False),
        EventTypeSpec(PluginEvent.DISABLED, "Plugin disabled", "Plugins", trigger=False),
        EventTypeSpec(PluginEvent.UNINSTALLED, "Plugin uninstalled", "Plugins", trigger=False),
    ),
)
