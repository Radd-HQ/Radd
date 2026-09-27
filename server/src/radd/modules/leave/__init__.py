from radd.kernel import EventTypeSpec, IntegrationSpec, PluginUiManifest, RaddPlugin
from radd.kernel.sockets import Socket

from .availability import LeaveAvailability
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
    ui=PluginUiManifest(remote="/plugins/leave/remoteEntry.js", ui_api_version="2.0.0"),
    event_types=(
        # RADD-1320: WHO is away — a person or a team, never both (holidays neither).
        EventTypeSpec(LeaveEvent.CREATED, "Leave recorded", "People", subjects=("user", "team")),
        EventTypeSpec(LeaveEvent.DELETED, "Leave removed", "People", subjects=("user", "team")),
    ),
    # Sockets, so neither `slas` (holidays, RADD-1031) nor round-robin assignment
    # (who is away, RADD-1387) imports leave, and disabling it withdraws both.
    integrations=(
        IntegrationSpec(Socket.NON_WORKING_DAYS, "leave_holidays", impl=HolidayCalendar()),
        IntegrationSpec(Socket.PERSON_AVAILABILITY, "leave_absences", impl=LeaveAvailability()),
    ),
)
