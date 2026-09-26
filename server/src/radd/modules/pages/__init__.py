"""Pages (spec 43): spaces, page trees, version history, issue↔page links, live
FTS. A single-writer PATCH carries `expected_version`; live co-editing is the
`collab` plugin (spec 122)."""

from radd.kernel import EntityLinkSpec
from radd.kernel import IntegrationSpec
from radd.kernel import EntityRefSpec
from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import PermissionSpec
from radd.kernel import SettingSpec
from radd.kernel.sockets import Socket

from . import refs
from .search_source import PageDocuments
from .searchable import PAGE_SEARCHABLE

from . import attachments_binding as attachments_binding  # registers the page parent
from . import comments_binding as comments_binding  # registers the page comment parent
from .extensions import PAGE_EXTENSIONS
from .grantscope import SPACE_SCOPE
from .router import router
from .types import PageEntity, PageEvent

from .page_access import _PAGE_SPEC

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools
from .automation import COMMENT_NODE, MOVE_NODE, PAGE_TOKENS, SPACE_GATE
from .notifications import PAGE_NOTIFICATIONS

plugin = RaddPlugin(
    name="pages",
    entity_links=(
        EntityLinkSpec('page_space', ('/settings/pages',)),
        EntityLinkSpec('page', ('/pages?pageId={refs.page.number}', '/pages?pageId={refs.page.id}')),
    ),
    automation_nodes=(COMMENT_NODE, MOVE_NODE, SPACE_GATE),
    searchables=(PAGE_SEARCHABLE,),  # RADD-1327
    token_providers=(PAGE_TOKENS,),
    # RADD-791: SPACE-scoped. RADD-1305: manage ⇒ write ⇒ read (transitive).
    permissions=(
        PermissionSpec(
            "page.read", "space", "Read a wiki space and its pages.", implied_by=("page.write",)
        ),
        PermissionSpec(
            "page.write", "space", "Create and edit pages in a space; link them to issues.",
            implied_by=("page.manage",),
        ),
        PermissionSpec(
            "page.manage", "space", "Manage a space; hard-delete and restore its pages."
        ),
        PermissionSpec("page.delete", "space", "Hard-delete pages.", implied_by=("page.manage",)),
    ),
    # Spec 122: the history window a collaborative session's autosaves obey.
    settings_keys=(
        SettingSpec(
            key="page_collab_version_window_seconds",
            type="int",
            scopes=("instance",),
            label="Wiki: history window for live co-editing",
            description=(
                "While a page is co-edited live, an autosave records a history "
                "version only when the previous one is older than this many seconds "
                "(the session's final save always does). A person's history is a "
                "list of work sessions, not of pauses in typing."
            ),
            section="pages",
        ),
    ),
    # RADD-818: on the manifest, because the loader's clear() wipes import-time registration.
    access_resources=(_PAGE_SPEC,),
    description=(
        "The wiki: page spaces, page trees, version history and links to issues."
    ),
    depends_on=("events", "projects", "auth", "workflow", "items", "attachments", "labels", "comments", "notify", "access", "groups", "search", "teams", "settings"),
    routers=(router,),
    # RADD-923: subjects other modules name (notify scopes a subscription to a
    # SPACE id and links by slug) without importing this module.
    entity_refs=(
        EntityRefSpec("page", refs.page_ref, label="Page"),
        EntityRefSpec("page_space", refs.space_ref, label="Page space"),
    ),
    event_types=(
        EventTypeSpec(PageEvent.SPACE_CREATED, "Page space created", "Pages"),
        EventTypeSpec(
            PageEvent.SPACE_PUBLIC_ACCESS_CHANGED, "Page space public access changed", "Pages",
            has_changes=True, entity_type="page_space", subjects=("page_space",),
        ),
        EventTypeSpec(PageEvent.SPACE_UPDATED, "Page space updated", "Pages", has_changes=True),
        EventTypeSpec(PageEvent.SPACE_DELETED, "Page space deleted", "Pages"),
        # Every page event carries both refs; the loader refuses to boot a subject
        # nothing can resolve.
        EventTypeSpec(
            PageEvent.PAGE_CREATED, "Page created", "Pages", subjects=("page", "page_space")
        ),
        EventTypeSpec(
            PageEvent.PAGE_UPDATED, "Page updated", "Pages",
            has_changes=True, subjects=("page", "page_space")
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
    # RADD-889: disabling this plugin removes its MCP tools from catalog + dispatch.
    mcp_tools=mcptools.MCP_TOOLS,
    # Kernel sockets, so a runtime disable withdraws both: documents for search
    # (RADD-1384) and the page as a notification SUBJECT (RADD-1385).
    integrations=(
        IntegrationSpec(Socket.SEARCH_DOCUMENTS, PageEntity.PAGE.value, impl=PageDocuments()),
        IntegrationSpec(
            Socket.NOTIFICATION_SUBJECT, PageEntity.PAGE.value, impl=PAGE_NOTIFICATIONS
        ),
    ),
)
