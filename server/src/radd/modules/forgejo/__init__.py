from radd.kernel import CapabilitySpec
from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec

from . import service
from .admin_router import router as admin_router
from .models import ForgejoConnection, ForgejoRepo  # noqa: F401 — Alembic autogenerate
from .router import router
from .types import ForgejoEvent


def _admin_event(event_type: ForgejoEvent, label: str, entity: str) -> EventTypeSpec:
    """Spec 123: connector administration is audited with a diff; not a trigger."""
    return EventTypeSpec(
        event_type, label, "Admin",
        has_changes=event_type.endswith(".updated"), trigger=False, entity_type=entity,
    )

plugin = RaddPlugin(
    name="forgejo",
    # Spec 111: hosts and their repositories. No coarse verb of its own — the
    # umbrella is global.manage, the dashboard precedent.
    crud_resources=(
        CrudResourceSpec(
            "vcsconn", "global", "version-control connections", "global.manage"
        ),
    ),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Forgejo/Gitea connector (specs 47, 111): hosts and repositories as rows, a "
    "webhook receiver auto-linking branches/commits/PRs to items via the vcs seam, "
    "and merge transitions.",
    depends_on=("events", "projects", "auth", "workflow", "items", "vcs", "automations", "releases"),
    event_types=(
        _admin_event(ForgejoEvent.CONNECTION_CREATED, "Forgejo connection created", "forgejo_connection"),
        _admin_event(ForgejoEvent.CONNECTION_UPDATED, "Forgejo connection updated", "forgejo_connection"),
        _admin_event(ForgejoEvent.CONNECTION_DELETED, "Forgejo connection deleted", "forgejo_connection"),
        _admin_event(ForgejoEvent.REPO_CREATED, "Forgejo repository added", "forgejo_repo"),
        _admin_event(ForgejoEvent.REPO_UPDATED, "Forgejo repository updated", "forgejo_repo"),
        _admin_event(ForgejoEvent.REPO_DELETED, "Forgejo repository removed", "forgejo_repo"),
    ),
    routers=(router, admin_router),
    # Spec 111: the env secret seeds ONE connection row, once (the spec-100/101 rule),
    # so an existing deployment keeps verifying webhooks across the upgrade.
    on_startup=(service.seed_from_env,),
    capabilities=(
        CapabilitySpec(
            "forgejo",
            "Forgejo connector",
            "connector",
            # Spec 111 made connections rows and the env secret SEED-ONLY, so the
            # pill counts ACTIVE rows (snapshot: sync check, refreshed on writes).
            check=lambda: {"enabled": service.active_connection_count() > 0},
        ),
    ),
)
