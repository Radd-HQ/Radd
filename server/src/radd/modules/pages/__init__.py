"""Pages (spec 43; renamed from "docs"/"wiki"/"knowledge base" in RADD-701): page spaces, page trees, markdown bodies, full version
history, issue↔page links, and live FTS search.

Single-editor concurrency: PATCH carries `expected_version` and 409s when
stale (the PLAN §9 fallback — CRDT co-editing can land later behind the same
PATCH contract).
"""

from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from . import attachments_binding  # registers the page parent (spec 102)
from .extensions import PAGE_EXTENSIONS
from .public_router import router as public_router
from .router import router
from .types import PageEvent

plugin = RaddPlugin(
    name="pages",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Pages: page spaces + page trees (markdown bodies), optimistic-concurrency "
        "edits with full version history + restore, issue↔page links, and live "
        "Postgres FTS search over titles/bodies. Spec 74 adds opt-in PUBLIC "
        "spaces readable without login under /public/pages (trees, page bodies, "
        "public-only FTS)."
    ),
    depends_on=("events", "projects", "auth", "workflow", "items", "attachments"),
    routers=(router, public_router),
    event_types=(
        EventTypeSpec(PageEvent.SPACE_CREATED, "Page space created", "Pages"),
        EventTypeSpec(PageEvent.SPACE_UPDATED, "Page space updated", "Pages"),
        EventTypeSpec(PageEvent.SPACE_DELETED, "Page space deleted", "Pages"),
        EventTypeSpec(PageEvent.PAGE_CREATED, "Page created", "Pages"),
        EventTypeSpec(PageEvent.PAGE_UPDATED, "Page updated", "Pages"),
        EventTypeSpec(PageEvent.PAGE_DELETED, "Page deleted", "Pages"),
        EventTypeSpec(PageEvent.PAGE_MOVED, "Page moved", "Pages"),
        EventTypeSpec(PageEvent.PAGE_RESTORED, "Page restored", "Pages"),
        EventTypeSpec(PageEvent.LINK_CREATED, "Page↔issue link added", "Pages", item_scoped=True),
        EventTypeSpec(PageEvent.LINK_DELETED, "Page↔issue link removed", "Pages", item_scoped=True),
    ),
    page_extensions=PAGE_EXTENSIONS,
)
