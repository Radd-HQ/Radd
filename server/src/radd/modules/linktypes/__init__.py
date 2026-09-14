from radd.kernel import EventTypeSpec, RaddPlugin

from .router import router
from .service import ensure_builtins
from .types import LinkTypeEvent

plugin = RaddPlugin(
    name="linktypes",
    # RADD-1168: emitted since spec 91 and never registered. Not triggers.
    event_types=(
        EventTypeSpec(LinkTypeEvent.CREATED, "Link type created", "Admin", trigger=False),
        EventTypeSpec(
            LinkTypeEvent.UPDATED, "Link type updated", "Admin", has_changes=True, trigger=False
        ),
        EventTypeSpec(LinkTypeEvent.DELETED, "Link type deleted", "Admin", trigger=False),
    ),
    description="User-definable, scopeable issue link types (spec 91) — the catalog "
    "items resolves link labels + symmetry through.",
    depends_on=("projects", "events", "auth"),
    weak_depends=("items",),
    routers=(router,),
    on_startup=(ensure_builtins,),
)
