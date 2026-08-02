from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .router import router
from .types import LabelEvent

plugin = RaddPlugin(
    name="labels",
    description="Global labels: free-form tags, auto-created on first use (automation-friendly).",
    depends_on=("projects", "events"),
    routers=(router,),
    event_types=(
        EventTypeSpec(LabelEvent.CREATED, "Label created", "Admin"),
    ),
)
