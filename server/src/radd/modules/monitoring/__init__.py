from radd.kernel import NavItemSpec, PluginUiManifest, RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="monitoring",
    ui=PluginUiManifest(
        remote="/plugins/monitoring/remoteEntry.js", ui_api_version="2.0.0",
        nav=(NavItemSpec(key="monitoring", label="Monitoring", path="/settings/monitoring",
                         section="settings", group="Server", icon="activity", order=115,
                         requires_admin=True),),
    ),
    core=False,  # optional — disable it and the endpoint disappears
    description=(
        "Server health for admins: database, background workers and search coverage."
    ),
    depends_on=("auth", "events"),
    routers=(router,),
)
