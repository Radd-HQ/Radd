from radd.kernel import EntityLinkSpec
from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from .types import ScreenEvent

plugin = RaddPlugin(
    name="screens",
    entity_links=(
        EntityLinkSpec('screen', ('/p/{project.key}/settings/screens',)),
    ),
    # RADD-1168: emitted since spec 55 and never registered. Not a trigger.
    event_types=(
        EventTypeSpec(
            ScreenEvent.UPDATED, "Screen layout updated", "Admin",
            has_changes=True, trigger=False, subjects=("project",),
        ),
    ),
    description="Screens: which fields an issue type shows, collapses or hides.",
    depends_on=("projects", "events", "auth", "fields", "itemtypes"),
    routers=(router,),
)
