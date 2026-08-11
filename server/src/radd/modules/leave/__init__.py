from radd.kernel import EventTypeSpec, IntegrationSpec, RaddPlugin
from radd.kernel.sockets import Socket

from .holidays import HolidayCalendar
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
    # RADD-1031: the holidays recorded here are dates nobody works, which is
    # what an SLA clock needs to skip. Contributed through the socket rather
    # than called directly, so `slas` never learns this module exists and
    # disabling leave withdraws the calendar with it (the clock then runs on
    # weekends-only, exactly as it did before).
    integrations=(
        IntegrationSpec(Socket.NON_WORKING_DAYS, "leave_holidays", impl=HolidayCalendar()),
    ),
)
