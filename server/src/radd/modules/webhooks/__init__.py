from radd.kernel import RaddPlugin

from . import dispatcher
from .router import router

plugin = RaddPlugin(
    name="webhooks",
    description="Standard-Webhooks dispatcher: signed deliveries with retries, fed by the outbox.",
    depends_on=("projects", "events", "auth"),
    routers=(router,),
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
)
