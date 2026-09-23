"""Plugin state, managed package storage and per-process live UI reconciliation."""

from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from . import live
from .types import PluginEvent

plugin = RaddPlugin(
    name="pluginmgr",
    description="Installs, enables and disables plugins.",
    depends_on=("auth", "events"),
    weak_depends=("access",),
    routers=(router,),
    on_startup=(live.start,),
    on_shutdown=(live.stop,),
    # Admin lifecycle events — registered for audit/webhooks but NOT automation
    # triggers (trigger=False), so they don't clutter the rule builder.
    event_types=(
        EventTypeSpec(PluginEvent.PACKAGE_UPLOADED, "Plugin package uploaded", "Plugins", trigger=False),
        EventTypeSpec(PluginEvent.PACKAGE_REMOVED, "Plugin package removed", "Plugins", trigger=False),
        EventTypeSpec(PluginEvent.INSTALLED, "Plugin installed", "Plugins", trigger=False),
        EventTypeSpec(PluginEvent.ENABLED, "Plugin enabled", "Plugins", trigger=False),
        EventTypeSpec(PluginEvent.DISABLED, "Plugin disabled", "Plugins", trigger=False),
        EventTypeSpec(PluginEvent.UNINSTALLED, "Plugin uninstalled", "Plugins", trigger=False),
        EventTypeSpec(
            PluginEvent.CONTRIBUTIONS_CHANGED, "Plugin contributions changed", "Plugins",
            has_changes=True, trigger=False,
        ),
    ),
)
