from radd.config import settings
from radd.kernel import CapabilitySpec
from radd.kernel import RaddPlugin

from . import service
from .admin_router import router as admin_router
from .models import ForgejoConnection, ForgejoRepo  # noqa: F401 — Alembic autogenerate
from .router import router

plugin = RaddPlugin(
    name="forgejo",
    core=False,  # optional plugin — disableable via the plugin manager
    description="Forgejo/Gitea connector (specs 47, 111): hosts and repositories as rows, a "
    "webhook receiver auto-linking branches/commits/PRs to items via the vcs seam, "
    "and merge transitions.",
    depends_on=("projects", "auth", "workflow", "items", "vcs", "automations", "releases"),
    routers=(router, admin_router),
    # Spec 111: the env secret seeds ONE connection row, once (the spec-100/101 rule),
    # so an existing deployment keeps verifying webhooks across the upgrade.
    on_startup=(service.seed_from_env,),
    capabilities=(
        CapabilitySpec(
            "forgejo",
            "Forgejo connector",
            "connector",
            check=lambda: {"enabled": bool(settings.forgejo_webhook_secret)},
        ),
    ),
)
