from radd.kernel import RaddPlugin
from radd.modules.vcs.connector_kit import manifest
from radd.modules.vcs.connector_kit.admin import admin_router

from .models import GithubConnection, GithubRepo  # noqa: F401 — Alembic autogenerate
from .router import router
from .service import CONNECTOR, store

plugin = RaddPlugin(
    name="github",
    # RADD-1435: the Settings → Version control tab is vcs's, drawn from CONNECTOR.
    entity_links=manifest.entity_links(CONNECTOR),
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "GitHub integration: links branches, commits and pull requests to issues, shows CI status, mirrors"
        " time logged with /spend on pull requests, and offers merges, CI results and releases as automation"
        " triggers."
    ),
    depends_on=("events", "projects", "auth", "items", "vcs", "automations"),
    event_types=(*manifest.admin_event_types(CONNECTOR), *CONNECTOR.triggers.specs()),
    routers=(router, admin_router(store)),
    integrations=(manifest.integration(CONNECTOR),),
    # RADD_GITHUB_WEBHOOK_SECRET seeds ONE connection row, once (the spec-101 rule).
    on_startup=(store.encrypt_plaintext_credentials, store.seed_from_env),  # RADD-1446: sweep first
    capabilities=(store.capability(),),
)
