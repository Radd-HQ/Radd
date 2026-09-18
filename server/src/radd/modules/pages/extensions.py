"""The first-party page extensions (RADD-709).

A name appears here only once the SPA can actually RENDER it — the menu offering
an entry that lands as an "unknown extension" card is a visibly broken product,
and `tests/test_page_extensions.py` fails the build for exactly that. So each
new extension's declaration ships in the commit that builds its renderer.

Declarations only. Rendering happens in the SPA, dispatched by name through its
own registry — the server never renders a page body, so a server-side renderer
here would be a second implementation of something nothing calls.

What these rows drive is the editor's INSERT MENU (`GET /pages/extensions`): the
menu is a function of what is installed, so a plugin contributing a
`PageExtensionSpec` appears in it with no edit to this file, and disabling that
plugin removes it again.
"""

from radd.kernel import PageExtensionSpec

from .types import PageExtensionName

#: `depth` recurs in several specs with the same meaning; one definition so the
#: forms agree on the bounds.
_DEPTH = {
    "type": "integer",
    "minimum": 1,
    "maximum": 6,
    "default": 3,
    "description": "How many levels deep to go.",
}


PAGE_EXTENSIONS: tuple[PageExtensionSpec, ...] = (
    PageExtensionSpec(
        name=PageExtensionName.TOC,
        label="Table of contents",
        description="This page's headings, optionally with the pages beneath it.",
        icon="list-tree",
        params_schema={
            "type": "object",
            "properties": {
                "subpages": {
                    "type": "boolean",
                    "default": False,
                    "description": "Also list the pages below this one.",
                },
                "depth": _DEPTH,
            },
        },
    ),
    PageExtensionSpec(
        name=PageExtensionName.CHILDREN,
        label="Child pages",
        description="The pages beneath this one — linked, or embedded in full.",
        icon="folder-tree",
        params_schema={
            "type": "object",
            "properties": {
                "depth": {**_DEPTH, "default": 1},
                # RADD-858: embed = transclude every child's live body (the
                # radd:include machinery per child), naturally ordered — one
                # unified page that updates itself as children arrive.
                "mode": {
                    "type": "string",
                    "enum": ["links", "embed"],
                    "default": "links",
                    "description": "links = a list; embed = each child's full content, live.",
                },
            },
        },
    ),
    PageExtensionSpec(
        name=PageExtensionName.CALLOUT,
        label="Callout",
        description="A tinted note: info, success, warning or danger.",
        icon="info",
        params_schema={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["info", "success", "warning", "danger"],
                    "default": "info",
                },
                "title": {"type": "string", "description": "Optional bold first line."},
                # `format` is what tells the generated form (RADD-747) to offer a
                # textarea rather than a one-line input. A hint in the schema, not
                # a name the SPA special-cases — a plugin's extension gets the same
                # treatment by declaring the same format.
                "text": {
                    "type": "string",
                    "format": "markdown",
                    "description": "Markdown body of the callout.",
                },
            },
        },
    ),
    PageExtensionSpec(
        name=PageExtensionName.BACKLINKS,
        label="Backlinks",
        description="Every page that links to this one.",
        icon="link",
        params_schema={"type": "object", "properties": {}},
    ),
    PageExtensionSpec(
        name=PageExtensionName.INCLUDE,
        label="Include a page",
        description="Render another page's body inline, live.",
        icon="between-horizontal-start",
        params_schema={
            "type": "object",
            "required": ["page"],
            "properties": {
                "page": {
                    "type": "string",
                    "description": "The page's path in this space (parent-slug/slug), its number, or <space-slug>:<path> for another space.",
                }
            },
        },
    ),
    PageExtensionSpec(
        name=PageExtensionName.LABEL_LIST,
        label="Pages by label",
        description="Every page carrying a label — an index that maintains itself.",
        icon="tags",
        params_schema={
            "type": "object",
            "required": ["label"],
            "properties": {
                "label": {"type": "string", "description": "The label name."},
                "space": {
                    "type": "string",
                    "description": "Limit to one space slug; omit for every space.",
                },
            },
        },
    ),
    # --- spec 117 -----------------------------------------------------------
    # Contributed for the Confluence importer, but ordinary extensions: a person
    # can insert any of them, and nothing about them knows about Confluence.
    PageExtensionSpec(
        name=PageExtensionName.UNSUPPORTED_MACRO,
        label="Unsupported macro",
        description="An imported macro Radd cannot render yet, kept verbatim.",
        icon="puzzle",
        params_schema={
            "type": "object",
            "required": ["macro"],
            "properties": {
                "macro": {"type": "string", "description": "The original macro's name."},
                "params": {
                    "type": "object",
                    "description": "The original macro's parameters, verbatim.",
                },
                "body": {
                    "type": "string",
                    "format": "markdown",
                    "description": "The macro's content, converted.",
                },
            },
        },
    ),
    PageExtensionSpec(
        name=PageExtensionName.EXPAND,
        label="Expand",
        description="A collapsible section — click the title to reveal it.",
        icon="chevron-right",
        params_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "default": "Details",
                    "description": "The always-visible summary line.",
                },
                "text": {
                    "type": "string",
                    "format": "markdown",
                    "description": "What the section reveals.",
                },
            },
        },
    ),
    PageExtensionSpec(
        name=PageExtensionName.ITEMS,
        label="Issue query",
        description="Issues matching an SLQ query, as a table.",
        icon="list-checks",
        params_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "An SLQ query over items, e.g. project = TD AND status = Open.",
                },
                # Kept when a Confluence `jiraissues` macro's JQL could not be
                # translated: the page then shows what the query WAS, rather than
                # a guess that returns plausible rows.
                "source_jql": {
                    "type": "string",
                    "description": "The original Jira query, when this came from an import.",
                },
                "unsupported": {
                    "type": "boolean",
                    "default": False,
                    "description": "Set when the original query needs rewriting by hand.",
                },
            },
        },
    ),
    PageExtensionSpec(
        name=PageExtensionName.MEDIA,
        label="Video or audio",
        description="Play an attached video or audio file in the page.",
        icon="play",
        params_schema={
            "type": "object",
            "required": ["src"],
            "properties": {
                "src": {
                    "type": "string",
                    "description": "The attachment's URL, or its filename on this page.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["video", "audio"],
                    "default": "video",
                    "description": "Which player to show.",
                },
                "title": {"type": "string", "description": "Caption under the player."},
                "poster": {"type": "string", "description": "Still image URL for video."},
            },
        },
    ),
    PageExtensionSpec(
        name=PageExtensionName.NEW_FROM_TEMPLATE,
        label="New page from template",
        description="A button that creates a child page from a template.",
        icon="file-plus",
        params_schema={
            "type": "object",
            "required": ["template"],
            "properties": {
                "template": {"type": "string", "description": "The template's name."},
                "label": {"type": "string", "description": "Button text."},
                "title_prompt": {
                    "type": "string",
                    "description": "What to ask for when naming the new page.",
                },
            },
        },
    ),
)
