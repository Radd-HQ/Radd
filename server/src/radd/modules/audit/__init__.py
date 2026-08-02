from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="audit",
    description=(
        "Admin audit trail: a read-only, filterable view over the append-only event "
        "log (actor, action, entity, time). No tables — the events outbox IS the log."
    ),
    depends_on=("events", "auth", "projects"),
    routers=(router,),
)
