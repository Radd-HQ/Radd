from radd.kernel import EntityLinkSpec
from radd.kernel import EventTypeSpec, NavItemSpec, PluginUiManifest, RaddPlugin
from radd.modules.attachments import hosts as storage_hosts

from . import connections, runs, snapshot
from .router import router
from .types import JiraEvent
from .routers import pipeline_router
from .snapshot import store as snapshot_store


def _admin_event(event_type: JiraEvent, label: str) -> EventTypeSpec:
    """Spec 123: connection administration is audited with a diff; not a trigger."""
    return EventTypeSpec(
        event_type, label, "Admin",
        has_changes=event_type.endswith(".updated"), trigger=False,
        entity_type="jira_connection",
    )


# Snapshot blobs live on a storage host through the spec-102 blob API; a host
# they still reference must not be deletable out from under them.
storage_hosts.register_use_check(snapshot_store.blob_count_for_host)

plugin = RaddPlugin(
    name="jiraimport",
    entity_links=(
        EntityLinkSpec('jira_connection', ('/settings/jira-import',)),
    ),
    event_types=(
        _admin_event(JiraEvent.CONNECTION_CREATED, "Jira connection created"),
        _admin_event(JiraEvent.CONNECTION_UPDATED, "Jira connection updated"),
        _admin_event(JiraEvent.CONNECTION_DELETED, "Jira connection deleted"),
    ),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Imports projects, issues and history from Jira Server or Data Center, reversibly.",
    depends_on=("auth", "projects", "fields", "items", "workflow", "comments", "cycles", "attachments", "events", "itemtypes", "linktypes", "notify", "releases", "timelogging", "weblinks", "teams"),
    # Deferred + feature-detected: `apply.py` suppresses spec-119 intake
    # validation around each item it writes, because an import is history rather
    # than somebody submitting a request.
    weak_depends=("automations",),
    on_startup=(
        # Seed a connection row from RADD_JIRA_* once (env is seed-only).
        connections.seed_from_env,
        # A run/download executes as an in-process asyncio task; a restart abandons
        # it, so anything left mid-flight is failed on startup rather than sitting
        # forever claiming to be running.
        runs.mark_interrupted,
        snapshot.download.mark_interrupted,
    ),
    routers=(router, pipeline_router),
    # The page is this plugin's remote; its link sits in the settings "Import"
    # group. Disabling the plugin withdraws both.
    ui=PluginUiManifest(
        remote="/plugins/jiraimport/remoteEntry.js", ui_api_version="1.14.0",
        nav=(NavItemSpec(key="jiraimport", label="Jira", path="/settings/jira-import",
                         section="settings", group="Import", icon="database-zap", order=10,
                         requires_admin=True),),
    ),
)
