from radd.kernel import RaddPlugin

from . import dispatcher
from .router import router

plugin = RaddPlugin(
    name="search",
    description="Postgres full-text search over items (key/title/description/public "
    "comments), maintained by an outbox indexer; GET /search for the palette + "
    "GET /search/deflect for KB deflection (spec 66 — docs is a deferred, "
    "feature-detected seam: it loads after search).",
    depends_on=("events", "projects", "auth", "workflow", "items", "comments", "access", "fields", "teams"),
    weak_depends=("ai", "pages"),
    routers=(router,),
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
)
