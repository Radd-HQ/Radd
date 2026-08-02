from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="monitoring",
    core=False,  # optional — disable it and the endpoint disappears
    description=(
        "Operator monitoring (admin-only): DB health + size, approximate entity "
        "counts, and every background consumer's event-stream lag — the data "
        "behind Settings → Monitoring. Embedding coverage stays on the ai module "
        "(the page composes both, so monitoring never depends on an optional "
        "plugin)."
    ),
    depends_on=("auth", "events"),
    routers=(router,),
)
