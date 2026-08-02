from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from . import subscribers  # noqa: F401  — registers the project-created hook
from .router import router
from .types import TypeEvent

plugin = RaddPlugin(
    name="itemtypes",
    description="Per-project issue types (Bug/Task/Story/…) — the classification axis, "
    "orthogonal to the epic/issue/subtask hierarchy; seeds defaults on project creation (spec 51).",
    depends_on=("projects", "events", "auth"),
    routers=(router,),
    event_types=(
        EventTypeSpec(TypeEvent.CREATED, "Issue type created", "Admin"),
        EventTypeSpec(TypeEvent.UPDATED, "Issue type updated", "Admin"),
    ),
)
