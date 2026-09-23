from radd.config import settings
from radd.kernel import CapabilitySpec
from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="alertmanager",
    core=False,  # optional plugin — disableable via the plugin manager
    description="Turns firing Prometheus Alertmanager alerts into issues, and repeats or resolutions into comments.",
    depends_on=("projects", "auth", "workflow", "items", "comments", "automations"),
    routers=(router,),
    capabilities=(
        CapabilitySpec(
            "alertmanager",
            "Alertmanager intake",
            "connector",
            check=lambda: {"enabled": bool(settings.alertmanager_token)},
        ),
    ),
)
