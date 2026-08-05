from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from .types import GroupEvent

plugin = RaddPlugin(
    name="groups",
    description=(
        "Directory groups (RADD-829): AD objects mirrored with their nesting. "
        "A group is never local and a team is never directory-mirrored — a "
        "local grouping is a Team; the directory's truth is a Group."
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
