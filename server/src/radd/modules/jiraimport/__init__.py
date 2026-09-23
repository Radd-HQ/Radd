from radd.kernel import EventTypeSpec, RaddPlugin
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
        # Carry a spec-90 environment configuration into a real connection row so
        # an existing deploy keeps working after the move to DB-managed connections.
        connections.seed_from_env,
        # A run/download executes as an in-process asyncio task; a restart abandons
        # it, so anything left mid-flight is failed on startup rather than sitting
        # forever claiming to be running.
        runs.mark_interrupted,
        snapshot.download.mark_interrupted,
    ),
    routers=(router, pipeline_router),
)
