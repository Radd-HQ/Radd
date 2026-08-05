from radd.kernel import RaddPlugin

from .router import router
from .service import ensure_builtins

plugin = RaddPlugin(
    name="linktypes",
    description="User-definable, scopeable issue link types (spec 91) — the catalog "
    "items resolves link labels + symmetry through.",
    depends_on=("projects", "events", "auth"),
    weak_depends=("items",),
    routers=(router,),
    on_startup=(ensure_builtins,),
)
