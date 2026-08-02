from radd.config import settings
from radd.kernel import CapabilitySpec
from radd.kernel import RaddPlugin

from .router import router

plugin = RaddPlugin(
    name="forgejo",
    core=False,  # optional plugin — disableable via the plugin manager
    description="Forgejo/Gitea connector (spec 47): webhook receiver auto-linking "
    "branches/commits/PRs to items via the vcs seam, with merge transitions.",
    depends_on=("projects", "auth", "workflow", "items", "vcs", "automations"),
    routers=(router,),
    capabilities=(
        CapabilitySpec(
            "forgejo",
            "Forgejo connector",
            "connector",
            check=lambda: {"enabled": bool(settings.forgejo_webhook_secret)},
        ),
    ),
)
