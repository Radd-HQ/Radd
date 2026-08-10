"""The Confluence importer (spec 117) — the wiki half of the migration.

Spec 100's machine, pointed at Confluence and writing into `pages` instead of
`items`: connections → a snapshot downloaded once → a plan of editable mappings →
a staged, silent, reversible run.

Server/DC only. Cloud would be a second `client.py` behind the same `service.py`.
"""

from radd.kernel import RaddPlugin

from . import connections, runs, snapshot
from .pipeline_router import pipeline_router
from .router import router

# No storage-host use check: a snapshot's bytes live in its own directory on disk
# (`snapshot/package.py`), not on a storage host, so no host is held hostage by a
# download that may never be imported.

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
