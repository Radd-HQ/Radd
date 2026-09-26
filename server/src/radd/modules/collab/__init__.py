"""Collaborative editing (spec 122): one live Yjs document per wiki page.

Join, then the socket; room state persists tagged with the page version; the
write guard on `pages`' hooks refuses body writes not from the room while an
editor is connected (`pages` never imports this module). The client is this
plugin's UI remote (RADD-1397)."""

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
