from radd.kernel import CapabilitySpec, RaddPlugin
from radd.kernel import EventTypeSpec

from . import service
from .admin_router import router as admin_router
from .models import GithubConnection, GithubRepo  # noqa: F401 — Alembic autogenerate
from .router import TRIGGERS, router
from .types import GithubEvent


def _admin_event(event_type: GithubEvent, label: str, entity: str) -> EventTypeSpec:
    """Spec 123: connector administration is audited with a diff; not a trigger."""
    return EventTypeSpec(
        event_type, label, "Admin",
        has_changes=event_type.endswith(".updated"), trigger=False, entity_type=entity,
    )

plugin = RaddPlugin(
    name="github",
    core=False,  # optional plugin — disableable via the plugin manager
    description="GitHub integration: links branches, commits and pull requests to issues, shows CI status, and offers merges, CI results and releases as automation triggers.",
    depends_on=("events", "projects", "auth", "items", "vcs", "automations"),
    event_types=(
        _admin_event(GithubEvent.CONNECTION_CREATED, "GitHub connection created", "github_connection"),
        _admin_event(GithubEvent.CONNECTION_UPDATED, "GitHub connection updated", "github_connection"),
        _admin_event(GithubEvent.CONNECTION_DELETED, "GitHub connection deleted", "github_connection"),
        _admin_event(GithubEvent.REPO_CREATED, "GitHub repository added", "github_repo"),
        _admin_event(GithubEvent.REPO_UPDATED, "GitHub repository updated", "github_repo"),
        _admin_event(GithubEvent.REPO_DELETED, "GitHub repository removed", "github_repo"),
        # RADD-1309: GitHub's own automation triggers — the connector acts on nothing itself.
        *TRIGGERS.specs(),
    ),
    routers=(router, admin_router),
    automation_templates=TRIGGERS.templates(),
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
