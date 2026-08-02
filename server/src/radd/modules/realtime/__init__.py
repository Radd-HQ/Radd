from radd.kernel import RaddPlugin

from . import broadcaster
from .router import router

plugin = RaddPlugin(
    name="realtime",
    description="WebSocket live updates: an ephemeral tail of the event outbox "
    "pushed to authenticated browser clients (entity-level invalidation signals).",
    depends_on=("events", "auth"),
    routers=(router,),
    on_startup=(broadcaster.start,),
    on_shutdown=(broadcaster.stop,),
)
