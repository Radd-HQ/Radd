from radd.kernel import NavItemSpec, PluginUiManifest, RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="monitoring",
    ui=PluginUiManifest(
        remote="/plugins/monitoring/remoteEntry.js", ui_api_version="1.3.0",
        nav=(NavItemSpec(key="monitoring", label="Monitoring", path="/settings/monitoring",
                         section="settings", group="Server", icon="Activity", order=115,
                         requires_admin=True),),
    ),
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
