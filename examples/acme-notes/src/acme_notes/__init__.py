"""acme-notes — an EXAMPLE external Radd plugin (spec 94 acceptance).

Everything a plugin needs, built entirely against the PUBLIC SDK (`radd.sdk`) with no import of Radd
internals, in a project that lives OUTSIDE the Radd source tree: a note entity (auto-wired table +
CRUD + events + RBAC), a nav item, and a federated UI remote (its own `web/` build) contributing a
Notes page and an issue-panel section. Radd discovers it via the `radd.plugins` entry point and
loads it at runtime — zero edits to Radd core or any other plugin.
"""

from radd.sdk import (
    NavItemSpec,
    PluginUiManifest,
    RaddPlugin,
    SlqFieldSpec,
    ViewTypeSpec,
    WidgetTypeSpec,
)

from .router import router
from .slq import note_item_ids
from .spec import NOTE

plugin = RaddPlugin(
    id="acme.notes",
    name="acme-notes",
    version="1.0.0",
    api_version="1.0.0",
    core=False,
    description="Example external plugin: issue notes + a Notes page (own project, own web build).",
    depends_on=("projects", "auth", "events", "items"),
    entities=(NOTE,),
    # The plugin's own server-side endpoint (GET /notes/stats) — server logic feeding the UI.
    routers=(router,),
    # Make issues searchable by note body in SLQ: `note ~ "text"` (spec 94).
    slq_fields=(SlqFieldSpec(name="note", label="Note body", item_ids=note_item_ids),),
    # A saved-view type (issue list + notes editor) and a dashboard widget type (recent notes),
    # rendered by this plugin's own view.type / dashboard.widget UI slots (spec 94).
    view_types=(ViewTypeSpec(key="acme.notes", label="Notes review"),),
    widget_types=(WidgetTypeSpec(key="acme.recent-notes", label="Most Recent Notes"),),
    ui=PluginUiManifest(
        nav=(
            NavItemSpec(
                key="acme-notes",
                label="Notes",
                path="/notes",
                icon="sticky-note",
                section="main",
                requires=("item.read",),
                order=60,
            ),
            # A Settings page (spec 94 settings.page slot): appears under Settings → Notes.
            NavItemSpec(
                key="acme-notes-settings",
                label="Notes",
                path="/settings/acme-notes",
                icon="sticky-note",
                section="settings",
                requires=("item.read",),
                order=90,
            ),
        ),
        remote="/plugins/acme-notes/remoteEntry.js",
        ui_api_version="1.0.0",
    ),
)
