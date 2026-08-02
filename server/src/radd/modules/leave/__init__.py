from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from .types import LeaveEvent

plugin = RaddPlugin(
    name="leave",
    core=False,  # optional feature module — disableable via the plugin manager
    description=(
        "Leave + team holidays: users record their own absences (team stewards "
        "cover for members, admins define per-team public holidays); the "
        "timesheet renders leave days, and one /leave/current query powers the "
        "app-wide dimmed-avatar indicator."
    ),
    depends_on=("auth", "teams", "events"),
    routers=(router,),
    event_types=(
        EventTypeSpec(LeaveEvent.CREATED, "Leave recorded", "People"),
        EventTypeSpec(LeaveEvent.DELETED, "Leave removed", "People"),
    ),
)
