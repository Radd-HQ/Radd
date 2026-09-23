from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec

from .router import team_router
from .types import TeamEvent

plugin = RaddPlugin(
    name="teams",
    crud_resources=(
        CrudResourceSpec(
            "team", "global", "teams", "global.manage",
            actions=("create", "read", "update", "delete"),
        ),
    ),
    description="Teams: groups of people you can give access to projects.",
    depends_on=("events", "projects", "auth", "groups"),
    weak_depends=("access", "items"),
    routers=(team_router,),
    event_types=(
        EventTypeSpec(TeamEvent.CREATED, "Team created", "Admin"),
        EventTypeSpec(TeamEvent.UPDATED, "Team updated", "Admin", has_changes=True),
        EventTypeSpec(TeamEvent.DELETED, "Team deleted", "Admin", trigger=False),
    ),
)
