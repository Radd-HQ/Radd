"""The Confluence importer (spec 117) — the wiki half of the migration.

Spec 100's machine, pointed at Confluence and writing into `pages` instead of
`items`: connections → a snapshot downloaded once → a plan of editable mappings →
a staged, silent, reversible run.

Server/DC only. Cloud would be a second `client.py` behind the same `service.py`.
"""

from radd.kernel import EventTypeSpec, RaddPlugin

from . import connections, runs, snapshot
from .pipeline_router import pipeline_router
from .router import router
from .types import ConfluenceEvent


def _admin_event(event_type: ConfluenceEvent, label: str) -> EventTypeSpec:
    """Spec 123: connection administration is audited with a diff; not a trigger."""
    return EventTypeSpec(
        event_type, label, "Admin",
        has_changes=event_type.endswith(".updated"), trigger=False,
        entity_type="confluence_connection",
    )

# No storage-host use check: a snapshot's bytes live in its own directory on disk
# (`snapshot/package.py`), not on a storage host, so no host is held hostage by a
# download that may never be imported.

plugin = RaddPlugin(
    name="confluenceimport",
    event_types=(
        _admin_event(ConfluenceEvent.CONNECTION_CREATED, "Confluence connection created"),
        _admin_event(ConfluenceEvent.CONNECTION_UPDATED, "Confluence connection updated"),
        _admin_event(ConfluenceEvent.CONNECTION_DELETED, "Confluence connection deleted"),
    ),
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Imports spaces and pages from Confluence Server or Data Center."
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
