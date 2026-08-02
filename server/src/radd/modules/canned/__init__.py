from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="canned",
    description="Canned responses: globally-managed comment snippets for the "
    "service-desk reply flow (spec 30) + per-item {{token}} rendering (spec 66).",
    depends_on=("events", "projects", "auth", "items"),
    routers=(router,),
)
