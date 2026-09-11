"""Pages (spec 43; renamed from "docs"/"wiki"/"knowledge base" in RADD-701): page spaces, page trees, markdown bodies, full version
history, issue↔page links, and live FTS search.

Single-editor concurrency: PATCH carries `expected_version` and 409s when
stale (the PLAN §9 fallback — CRDT co-editing can land later behind the same
PATCH contract).
"""

from radd.kernel import EntityRefSpec
from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import PermissionSpec

from . import refs

from . import attachments_binding as attachments_binding  # registers the page parent (spec 102)
from . import comments_binding as comments_binding  # registers the page comment parent (RADD-717)
from .extensions import PAGE_EXTENSIONS
from .grantscope import SPACE_SCOPE
from .public_router import router as public_router
from .router import router
from .types import PageEvent

from .page_access import _PAGE_SPEC

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools

plugin = RaddPlugin(
    name="pages",
    # RADD-791: SPACE-scoped. They were global because a page had no scope to be
    # checked against, which made per-space access inexpressible.
    permissions=(
        PermissionSpec("page.read", "space", "Read a wiki space and its pages."),
        PermissionSpec(
            "page.write", "space", "Create and edit pages in a space; link them to issues."
        ),
        PermissionSpec(
            "page.manage", "space", "Manage a space; hard-delete and restore its pages."
        ),
        PermissionSpec("page.delete", "space", "Hard-delete pages.", implied_by=("page.manage",)),
    ),
    # RADD-818: spec-92 resources ride the MANIFEST — the loader's clear()
    # wipes import-time registration, and the manifest is what survives it.
    access_resources=(_PAGE_SPEC,),
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Pages: page spaces + page trees (markdown bodies), optimistic-concurrency "
        "edits with full version history + restore, issue↔page links, and live "
        "Postgres FTS search over titles/bodies. Spec 74 adds opt-in PUBLIC "
        "spaces readable without login under /public/pages (trees, page bodies, "
        "public-only FTS)."
    ),
    depends_on=("events", "projects", "auth", "workflow", "items", "attachments", "labels", "comments", "notify", "access", "groups", "search", "teams"),
    weak_depends=("ai",),
    routers=(router, public_router),
    # RADD-923: a page and a space are subjects other modules name. Spec 118 is
    # what forced them — `notify` scopes a wiki subscription to a SPACE id and
    # links a notification by slug, and it may reach neither through this
    # module's models (the spine rule) nor by importing it (it loads first).
    entity_refs=(
        EntityRefSpec("page", refs.page_ref, label="Page"),
        EntityRefSpec("page_space", refs.space_ref, label="Page space"),
    ),
    event_types=(
        EventTypeSpec(PageEvent.SPACE_CREATED, "Page space created", "Pages"),
        EventTypeSpec(PageEvent.SPACE_UPDATED, "Page space updated", "Pages"),
        EventTypeSpec(PageEvent.SPACE_DELETED, "Page space deleted", "Pages"),
        # Every page event carries both refs. Declaring the subject is what makes
        # the promise checkable: the loader refuses to boot a plugin whose events
        # name a subject nothing can resolve, so the payload cannot silently lose
        # the space that a subscription is matched on.
        EventTypeSpec(
            PageEvent.PAGE_CREATED, "Page created", "Pages", subjects=("page", "page_space")
        ),
        EventTypeSpec(
            PageEvent.PAGE_UPDATED, "Page updated", "Pages", subjects=("page", "page_space")
        ),
        EventTypeSpec(
            PageEvent.PAGE_DELETED, "Page deleted", "Pages", subjects=("page", "page_space")
        ),
        EventTypeSpec(
            PageEvent.PAGE_MOVED, "Page moved", "Pages", subjects=("page", "page_space")
        ),
        EventTypeSpec(
            PageEvent.PAGE_RESTORED, "Page restored", "Pages", subjects=("page", "page_space")
        ),
        EventTypeSpec(PageEvent.LINK_CREATED, "Page↔issue link added", "Pages", item_scoped=True),
        EventTypeSpec(PageEvent.LINK_DELETED, "Page↔issue link removed", "Pages", item_scoped=True),
    ),
    page_extensions=PAGE_EXTENSIONS,
    # RADD-892: a space is a grant scope, and only pages can name/count one.
    grant_scopes=(SPACE_SCOPE,),
    # RADD-889: the doc tools of the spec-45 MCP catalog live with their owner —
    # registration replaces the mcp pages_bridge feature probe, so disabling this
    # plugin removes them from catalog + dispatch together.
    mcp_tools=mcptools.MCP_TOOLS,
)
