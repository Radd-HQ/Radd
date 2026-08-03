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
        description="A list of the pages directly beneath this one.",
        icon="folder-tree",
        params_schema={
            "type": "object",
            "properties": {"depth": {**_DEPTH, "default": 1}},
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
                    "description": "The page's slug, or <space-slug>/<page-slug>.",
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
