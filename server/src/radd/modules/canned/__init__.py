from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec

from .router import router

plugin = RaddPlugin(
    name="canned",
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
