from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from .types import ScreenEvent

plugin = RaddPlugin(
    name="screens",
    # RADD-1168: emitted since spec 55 and never registered. Not a trigger.
    event_types=(
        EventTypeSpec(
            ScreenEvent.UPDATED, "Screen layout updated", "Admin",
            has_changes=True, trigger=False, subjects=("project",),
        ),
    ),
    description="Field-layout (screen) config per (project, issue-type): which fields are "
    "primary / secondary-collapsed / hidden in the issue view (presentation only).",
    depends_on=("projects", "events", "auth", "fields", "itemtypes"),
    routers=(router,),
)
