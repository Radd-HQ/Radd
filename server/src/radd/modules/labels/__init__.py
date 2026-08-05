from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec

from .router import router
from .types import LabelEvent

plugin = RaddPlugin(
    name="labels",
    # RADD-816 (F6): label.read is a deliverable atom — Baseline-seeded, so day-one
    # behaviour is the old member floor, but REVOCABLE for the first time.
    crud_resources=(
        CrudResourceSpec(
            "label", "global", "labels", "global.manage",
            actions=("create", "read", "update", "delete"),
        ),
    ),
    description="Global labels: free-form tags, auto-created on first use (automation-friendly).",
    depends_on=("projects", "events", "auth"),
    routers=(router,),
    event_types=(
        EventTypeSpec(LabelEvent.CREATED, "Label created", "Admin"),
    ),
)
