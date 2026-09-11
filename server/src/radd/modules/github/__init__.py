from radd.kernel import CapabilitySpec, RaddPlugin

from . import service
from .admin_router import router as admin_router
from .models import GithubConnection, GithubRepo  # noqa: F401 — Alembic autogenerate
from .router import router

plugin = RaddPlugin(
    name="github",
    core=False,  # optional plugin — disableable via the plugin manager
    description="GitHub connector (RADD-1129): hosts and repositories as rows, an "
    "X-Hub-Signature-256 webhook receiver auto-linking branches/commits/PRs to items via "
    "the vcs seam, CI state from check runs, merge transitions, release sweeps and an "
    "API backfill. Administration reuses the vcsconn.* atoms the forgejo connector "
    "declares (one resource: version-control connections).",
    depends_on=("projects", "auth", "workflow", "items", "vcs", "automations", "releases"),
    routers=(router, admin_router),
    # RADD_GITHUB_WEBHOOK_SECRET seeds ONE connection row, once (the spec-101 rule).
    on_startup=(service.seed_from_env,),
    capabilities=(
        CapabilitySpec(
            "github",
            "GitHub connector",
            "connector",
            check=lambda: {"enabled": service.active_connection_count() > 0},
        ),
    ),
)
