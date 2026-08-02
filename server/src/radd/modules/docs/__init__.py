"""Wiki (spec 43): doc spaces, page trees, markdown bodies, full version
history, issue↔doc links, and live FTS search.

Single-editor concurrency: PATCH carries `expected_version` and 409s when
stale (the PLAN §9 fallback — CRDT co-editing can land later behind the same
PATCH contract).
"""

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from . import attachments_binding  # registers the doc_page parent (spec 102)
from .public_router import router as public_router
from .router import router
from .types import DocEvent

plugin = RaddPlugin(
    name="docs",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Wiki: doc spaces + page trees (markdown bodies), optimistic-concurrency "
        "edits with full version history + restore, issue↔doc links, and live "
        "Postgres FTS search over titles/bodies. Spec 74 adds opt-in PUBLIC "
        "spaces readable without login under /public/kb (trees, page bodies, "
        "public-only FTS)."
    ),
    depends_on=("events", "projects", "auth", "workflow", "items", "attachments"),
    routers=(router, public_router),
    event_types=(
        EventTypeSpec(DocEvent.SPACE_CREATED, "Doc space created", "Docs"),
        EventTypeSpec(DocEvent.SPACE_UPDATED, "Doc space updated", "Docs"),
        EventTypeSpec(DocEvent.SPACE_DELETED, "Doc space deleted", "Docs"),
        EventTypeSpec(DocEvent.PAGE_CREATED, "Doc page created", "Docs"),
        EventTypeSpec(DocEvent.PAGE_UPDATED, "Doc page updated", "Docs"),
        EventTypeSpec(DocEvent.PAGE_DELETED, "Doc page deleted", "Docs"),
        EventTypeSpec(DocEvent.PAGE_MOVED, "Doc page moved", "Docs"),
        EventTypeSpec(DocEvent.PAGE_RESTORED, "Doc page restored", "Docs"),
        EventTypeSpec(DocEvent.LINK_CREATED, "Doc↔issue link added", "Docs", item_scoped=True),
        EventTypeSpec(DocEvent.LINK_DELETED, "Doc↔issue link removed", "Docs", item_scoped=True),
    ),
)
