from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="reporting",
    description=(
        "Read-only analytics computed on the fly from the event log + cycles: throughput, "
        "cumulative flow, time-in-state, velocity, burnup, and the SLA report (spec 63, over "
        "slas/report.py's bookkeeping seam). No tables, no migration — state history is "
        "reconstructed from item.created/item.updated payloads (spec 16). Soft-coupled to "
        "slas both ways (slas reads timeline.py, /reports/sla reads slas/report.py) — "
        "undeclarable in depends_on without a load-order cycle; see docs/modules.md."
    ),
    depends_on=("events", "projects", "auth", "workflow", "cycles", "items"),
    weak_depends=("csat", "slas"),
    routers=(router,),
)
