from radd.kernel import EventTypeSpec, RaddPlugin
from radd.kernel import CrudResourceSpec

from .router import router
from .types import CannedEvent

plugin = RaddPlugin(
    name="canned",
    # RADD-1168: emitted since spec 30 and never registered. Not triggers.
    event_types=(
        EventTypeSpec(CannedEvent.CREATED, "Canned response created", "Service desk", trigger=False),
        EventTypeSpec(
            CannedEvent.UPDATED, "Canned response updated", "Service desk",
            has_changes=True, trigger=False,
        ),
        EventTypeSpec(CannedEvent.DELETED, "Canned response deleted", "Service desk", trigger=False),
    ),
    crud_resources=(
        CrudResourceSpec(
            "canned", "global", "canned responses", "global.manage",
            actions=("create", "read", "update", "delete"),
        ),
    ),
    description="Canned responses: globally-managed comment snippets for the "
    "service-desk reply flow (spec 30) + per-item {{token}} rendering (spec 66).",
    depends_on=("events", "projects", "auth", "items"),
    routers=(router,),
)
