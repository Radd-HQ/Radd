from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .router import router
from .types import VcsEvent

plugin = RaddPlugin(
    name="vcs",
    description="Version-control references (branches, commits, MRs/PRs) linked to work items; connector-populated dev panel.",
    depends_on=("projects", "auth", "events", "items"),
    routers=(router,),
    event_types=(
        EventTypeSpec(VcsEvent.LINKED, "VCS ref linked", "Links", item_scoped=True),
        EventTypeSpec(
            VcsEvent.UPDATED, "VCS ref updated", "Links", item_scoped=True, has_changes=True
        ),
        EventTypeSpec(VcsEvent.UNLINKED, "VCS ref unlinked", "Links", item_scoped=True),
    ),
)
