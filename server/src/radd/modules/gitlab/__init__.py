from radd.config import settings
from radd.kernel import CapabilitySpec
from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="gitlab",
    core=False,  # optional plugin — disableable via the plugin manager
    description="GitLab connector (spec 31): webhook receiver auto-linking "
    "branches/commits/MRs to items via the vcs seam, with merge transitions.",
    depends_on=("projects", "auth", "workflow", "items", "vcs", "automations"),
    routers=(router,),
    capabilities=(
        CapabilitySpec(
            "gitlab",
            "GitLab connector",
            "connector",
            check=lambda: {"enabled": bool(settings.gitlab_webhook_secret)},
        ),
    ),
)
