from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="monitoring",
    core=False,  # optional — disable it and the endpoint disappears
    description=(
        "Server health for admins: database, background workers and search coverage."
    ),
    depends_on=("auth", "events"),
    # RADD-1036: `mail_health` is mailintake's own seam — the aggregation lives
    # beside the code that emits `mail.failed`, so this module learns neither the
    # event type nor the payload shape. Reached DEFERRED and feature-detected,
    # because mailintake is optional and disableable; absent, the card is simply
    # not there.
    weak_depends=("mailintake",),
    routers=(router,),
)
