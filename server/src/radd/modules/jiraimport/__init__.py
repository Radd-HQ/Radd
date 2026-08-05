from radd.kernel import RaddPlugin
from radd.modules.attachments import hosts as storage_hosts

from . import connections, runs, snapshot
from .router import router
from .routers import pipeline_router
from .snapshot import store as snapshot_store

# Snapshot blobs live on a storage host through the spec-102 blob API; a host
# they still reference must not be deletable out from under them.
storage_hosts.register_use_check(snapshot_store.blob_count_for_host)

plugin = RaddPlugin(
    name="jiraimport",
    core=False,  # optional plugin — disableable via the plugin manager
    description="Jira import wizard (specs 90, 100): admin-managed Jira Server/DC "
    "connections — list projects, run JQL, infer an inbound schema, map fields to "
    "local custom fields, and run staged background imports.",
    depends_on=("auth", "projects", "fields", "items", "workflow", "comments", "cycles", "attachments", "events", "itemtypes", "linktypes", "notify", "releases", "timelogging", "weblinks"),
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
