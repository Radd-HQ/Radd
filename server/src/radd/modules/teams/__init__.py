from radd.kernel import PluginUiManifest, EntityRefSpec, EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec

from . import service
from .router import team_router
from .types import TeamEvent

plugin = RaddPlugin(
    name="teams",
    ui=PluginUiManifest(remote="/plugins/teams/remoteEntry.js", ui_api_version="1.6.0"),
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
    # RADD-1320: a team is an event subject.
    entity_refs=(EntityRefSpec("team", service.team_ref, label="Team"),),
    event_types=(
        EventTypeSpec(TeamEvent.CREATED, "Team created", "Admin", subjects=("team",)),
        EventTypeSpec(TeamEvent.UPDATED, "Team updated", "Admin", has_changes=True, subjects=("team",)),
        EventTypeSpec(TeamEvent.DELETED, "Team deleted", "Admin", trigger=False, subjects=("team",)),
    ),
)
