from radd.kernel import EventTypeSpec, IntegrationSpec, PluginUiManifest, RaddPlugin
from radd.kernel.sockets import Socket

from .holidays import HolidayCalendar
from .router import router
from .types import LeaveEvent

plugin = RaddPlugin(
    name="leave",
    core=False,  # optional feature module — disableable via the plugin manager
    description=(
        "Leave and team holidays, shown on the timesheet and beside people's names."
    ),
    depends_on=("auth", "teams", "events"),
    routers=(router,),
    ui=PluginUiManifest(remote="/plugins/leave/remoteEntry.js", ui_api_version="1.0.0"),
    event_types=(
        # RADD-1320: WHO is away — a person or a team, never both (holidays neither).
        EventTypeSpec(LeaveEvent.CREATED, "Leave recorded", "People", subjects=("user", "team")),
        EventTypeSpec(LeaveEvent.DELETED, "Leave removed", "People", subjects=("user", "team")),
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
