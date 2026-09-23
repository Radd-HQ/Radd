from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="reporting",
    description=(
        "Reports: throughput, cumulative flow, velocity, burnup and SLA performance."
    ),
    depends_on=("events", "projects", "auth", "workflow", "cycles", "items"),
    weak_depends=("csat", "slas"),
    routers=(router,),
)
