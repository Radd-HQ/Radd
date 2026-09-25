from radd.kernel import PluginUiManifest
from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from .types import GroupEvent

plugin = RaddPlugin(
    name="groups",
    ui=PluginUiManifest(remote="/plugins/groups/remoteEntry.js", ui_api_version="1.6.0"),
    description=(
        "Directory groups mirrored from Active Directory or LDAP, for granting access to whole groups."
    ),
    depends_on=("events", "auth"),
    weak_depends=("teams",),
    routers=(router,),
    event_types=(
        EventTypeSpec(GroupEvent.SYNCED, "Directory group synced", "Admin"),
        EventTypeSpec(GroupEvent.MISSING, "Directory group missing", "Admin"),
        EventTypeSpec(GroupEvent.RESTORED, "Directory group restored", "Admin"),
    ),
)
