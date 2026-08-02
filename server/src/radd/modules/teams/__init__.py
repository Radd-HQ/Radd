from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .router import project_team_router, team_router
from .types import TeamEvent

plugin = RaddPlugin(
    name="teams",
    description="Global teams, team membership, and project↔team role attachments.",
    depends_on=("events", "projects", "auth"),
    routers=(team_router, project_team_router),
    event_types=(
        EventTypeSpec(TeamEvent.CREATED, "Team created", "Admin"),
        EventTypeSpec(TeamEvent.UPDATED, "Team updated", "Admin"),
    ),
)
