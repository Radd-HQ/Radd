"""The Confluence importer (spec 117) — the wiki half of the migration.

Spec 100's machine, pointed at Confluence and writing into `pages` instead of
`items`: connections → a snapshot downloaded once → a plan of editable mappings →
a staged, silent, reversible run.

Server/DC only. Cloud would be a second `client.py` behind the same `service.py`.
"""

from radd.kernel import RaddPlugin

from . import connections
from .router import router

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
    ),
    routers=(router,),
)
