"""Collaborative editing (spec 122): one live Yjs document per wiki page.

Clients speak the y-websocket protocol over `WS /collab/pages/{id}` after a
`POST /collab/pages/{id}/join`; the room persists its state to
`page_collab_docs` tagged with the page version, and the write guard registered
on `pages`' hooks refuses any body write that did not come from the room while
an editor is connected. `pages` never imports this module.

The client is this plugin's UI remote (RADD-1397): it answers the pages' "is a
live session available?" (the SDK's `liveDocuments`) with a room, and binds the
host's editor to it through the editor's binding extension point. With the
plugin disabled the host ships and loads none of it.
"""

from radd.kernel import PluginUiManifest, RaddPlugin

from . import guard as guard  # registers the page hook handlers
from .rooms import hub
from .router import router

plugin = RaddPlugin(
    name="collab",
    description=(
        "Live co-editing of wiki pages, with presence."
    ),
    core=False,
    depends_on=("auth", "pages"),
    routers=(router,),
    on_startup=(hub.start,),
    on_shutdown=(hub.shutdown,),
    # UI API 1.17.0: live documents + the editor binding (RADD-1397).
    ui=PluginUiManifest(remote="/plugins/collab/remoteEntry.js", ui_api_version="1.17.0"),
)
