"""The Confluence importer (spec 117) — the wiki half of the migration.

Spec 100's machine, pointed at Confluence and writing into `pages` instead of
`items`: connections → a snapshot downloaded once → a plan of editable mappings →
a staged, silent, reversible run.

Server/DC only. Cloud would be a second `client.py` behind the same `service.py`.
"""

from radd.kernel import RaddPlugin
from radd.modules.attachments import hosts as storage_hosts

from . import connections, runs, snapshot
from .pipeline_router import pipeline_router
from .router import router
from .snapshot import store as snapshot_store

# Snapshot blobs live on a storage host through the spec-102 blob API; a host they
# still reference must not be deletable out from under them.
storage_hosts.register_use_check(snapshot_store.blob_count_for_host)

plugin = RaddPlugin(
    name="confluenceimport",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Confluence import wizard (spec 117): admin-managed Confluence Server/DC "
        "connections — download a space, a section or a set of pages once, map its "
        "macros and principals, then run a staged, reversible import into the wiki."
    ),
    depends_on=(
        "auth",
        "events",
        "pages",
        "attachments",
        "comments",
        "labels",
        "access",
        "groups",
        "teams",
        "items",
        "projects",
    ),
    on_startup=(
        # Carry an environment configuration into a real connection row so an
        # existing deploy keeps working after the move to DB-managed connections.
        connections.seed_from_env,
        # A download or a run executes as an in-process asyncio task; a restart
        # abandons it, so anything left mid-flight is failed rather than sitting
        # forever claiming to be running.
        snapshot.download.mark_interrupted,
        runs.mark_interrupted,
    ),
    routers=(router, pipeline_router),
)
