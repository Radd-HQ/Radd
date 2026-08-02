from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="events",
    description="Transactional outbox: append-only event log, the spine every consumer reads.",
    routers=(router,),
)
