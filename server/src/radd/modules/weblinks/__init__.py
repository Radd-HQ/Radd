from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .router import router
from .types import WebLinkEvent

plugin = RaddPlugin(
    name="weblinks",
    description="External/related URL links (docs, designs, references) attached to work items.",
    depends_on=("projects", "auth", "events", "items"),
    routers=(router,),
    event_types=(
        EventTypeSpec(WebLinkEvent.CREATED, "Web link added", "Links", item_scoped=True),
        EventTypeSpec(WebLinkEvent.UPDATED, "Web link edited", "Links", item_scoped=True),
        EventTypeSpec(WebLinkEvent.DELETED, "Web link removed", "Links", item_scoped=True),
    ),
)
