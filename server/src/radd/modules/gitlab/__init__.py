from radd.kernel import EventTypeSpec, RaddPlugin
from radd.modules.vcs.connector_kit import manifest
from radd.modules.vcs.connector_kit.admin import admin_router

from .models import GitlabConnection, GitlabRepo  # noqa: F401 — Alembic autogenerate
from .router import router
from .service import CONNECTOR, store
from .types import GitlabDeploymentOutcome, GitlabTrigger

plugin = RaddPlugin(
    name="gitlab",
    # RADD-1435: the Settings → Version control tab is vcs's, drawn from CONNECTOR.
    entity_links=manifest.entity_links(CONNECTOR),
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "GitLab integration: links branches, commits and merge requests to issues, shows CI status, mirrors"
        " time spent on merge requests, and offers merges, CI results, deployments and releases as automation"
        " triggers."
    ),
    depends_on=("events", "projects", "auth", "items", "vcs", "automations"),
    event_types=(
        *manifest.admin_event_types(CONNECTOR),
        *CONNECTOR.triggers.specs(),
        # RADD-1255: GitLab-only — neither GitHub nor Forgejo webhooks carry deployments.
        EventTypeSpec(
            GitlabTrigger.DEPLOYMENT_FINISHED, "GitLab: deployment finished", "GitLab",
            item_scoped=True, subjects=("item", "user"),
            payload_schema={"type": "object", "properties": {
                "environment": {"type": "string", "description": "e.g. staging, production"},
                "status": {"type": "string", "enum": [o.value for o in GitlabDeploymentOutcome]},
                "url": {"type": "string", "description": "The environment's URL (or the deploy job's)"},
                "ref": {"type": "object"},
                "sha": {"type": "string"},
            }},
        ),
    ),
    routers=(router, admin_router(store)),
    integrations=(manifest.integration(CONNECTOR),),
    # RADD_GITLAB_WEBHOOK_SECRET seeds ONE connection row, once (the spec-101 rule).
    on_startup=(store.encrypt_plaintext_credentials, store.seed_from_env),  # RADD-1446: sweep first
    capabilities=(store.capability(),),
)
