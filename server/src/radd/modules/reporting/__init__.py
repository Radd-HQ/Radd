from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="reporting",
    description="Reports: throughput, cumulative flow, time in state, velocity and burnup.",
    # RADD-1386: no edge to slas or csat. The SLA report is the slas plugin's
    # own; it folds with the public bucketing and scope helpers in service.py.
    depends_on=("events", "projects", "auth", "workflow", "cycles", "items"),
    routers=(router,),
)
