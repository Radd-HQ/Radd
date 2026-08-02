from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .router import router
from .types import ReleaseEvent

plugin = RaddPlugin(
    name="releases",
    description=(
        "Project-scoped releases/versions. Ordinary API resources a CI service-account "
        "or the automations engine can POST to and assign — replaces the CI-writes-labels hack."
    ),
    depends_on=("projects", "auth", "events"),
    routers=(router,),
    event_types=(
        EventTypeSpec(ReleaseEvent.CREATED, "Release created", "Releases"),
        EventTypeSpec(ReleaseEvent.UPDATED, "Release updated", "Releases"),
        EventTypeSpec(ReleaseEvent.DELETED, "Release deleted", "Releases"),
    ),
)
