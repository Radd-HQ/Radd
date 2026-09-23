from radd.kernel import CapabilitySpec, EventTypeSpec, RaddPlugin

from . import service
from .admin_router import router as admin_router
from .models import GitlabConnection, GitlabRepo  # noqa: F401 — Alembic autogenerate
from .router import router
from .types import GitlabEvent


def _admin_event(event_type: GitlabEvent, label: str, entity: str) -> EventTypeSpec:
    """Spec 123: connector administration is audited with a diff; not a trigger."""
    return EventTypeSpec(
        event_type, label, "Admin",
        has_changes=event_type.endswith(".updated"), trigger=False, entity_type=entity,
    )


plugin = RaddPlugin(
    name="gitlab",
    core=False,  # optional plugin — disableable via the plugin manager
    description="GitLab integration: links branches, commits and merge requests to issues and mirrors time spent on them.",
    depends_on=("events", "projects", "auth", "workflow", "items", "vcs", "automations", "releases"),
    event_types=(
        _admin_event(GitlabEvent.CONNECTION_CREATED, "GitLab connection created", "gitlab_connection"),
        _admin_event(GitlabEvent.CONNECTION_UPDATED, "GitLab connection updated", "gitlab_connection"),
        _admin_event(GitlabEvent.CONNECTION_DELETED, "GitLab connection deleted", "gitlab_connection"),
        _admin_event(GitlabEvent.REPO_CREATED, "GitLab project added", "gitlab_repo"),
        _admin_event(GitlabEvent.REPO_UPDATED, "GitLab project updated", "gitlab_repo"),
        _admin_event(GitlabEvent.REPO_DELETED, "GitLab project removed", "gitlab_repo"),
    ),
    routers=(router, admin_router),
    # RADD_GITLAB_WEBHOOK_SECRET seeds ONE connection row, once (the spec-101 rule).
    on_startup=(service.seed_from_env,),
    capabilities=(
        CapabilitySpec(
            "gitlab",
            "GitLab connector",
            "connector",
            check=lambda: {"enabled": service.active_connection_count() > 0},
        ),
    ),
)
