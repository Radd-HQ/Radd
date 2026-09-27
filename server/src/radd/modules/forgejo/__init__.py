from radd.kernel import RaddPlugin
from radd.modules.vcs.connector_kit import manifest
from radd.modules.vcs.connector_kit.admin import admin_router

from .models import ForgejoConnection, ForgejoRepo  # noqa: F401 — Alembic autogenerate
from .router import router
from .service import CONNECTOR, store

plugin = RaddPlugin(
    name="forgejo",
    # RADD-1435: the Settings → Version control tab is vcs's, drawn from CONNECTOR.
    entity_links=manifest.entity_links(CONNECTOR),
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Forgejo and Gitea integration: links branches, commits and pull requests to issues, shows CI"
        " status, mirrors time tracked on pull requests, and offers merges, CI results and releases as"
        " automation triggers."
    ),
    depends_on=("events", "projects", "auth", "items", "vcs", "automations"),
    event_types=(*manifest.admin_event_types(CONNECTOR), *CONNECTOR.triggers.specs()),
    routers=(router, admin_router(store)),
    integrations=(manifest.integration(CONNECTOR),),
    # Spec 111: the env secret seeds ONE connection row, once (the spec-101 rule).
    on_startup=(store.seed_from_env,),
    capabilities=(store.capability(),),
)
