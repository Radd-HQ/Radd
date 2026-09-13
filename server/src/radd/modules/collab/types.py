"""Wire vocabulary for the collab module (spec 122)."""

from enum import StrEnum

from pycrdt import YMessageType, YSyncMessageType


class CollabRole(StrEnum):
    """What a session may do to the live document. An observer's awareness
    (cursor, name) is relayed; its document updates are dropped at the seam."""

    EDITOR = "editor"
    OBSERVER = "observer"


class CollabEntity(StrEnum):
    SESSION = "collab_session"
    DOCUMENT = "page_collab_doc"


#: This module's id in the kernel registry — the plugin's `name`.
PLUGIN_ID = "collab"

#: WebSocket close codes (4000-range = application-defined). 4401 is the
#: realtime module's, kept numerically identical so a client has one meaning.
WS_CLOSE_UNAUTHENTICATED = 4401
#: `session` missing, unknown, for another user/page, or its room is gone —
#: the client must `POST …/join` again.
WS_CLOSE_SESSION_UNKNOWN = 4403
#: The page body was replaced by a write that did not come from this room
#: (an import, an MCP update while only observers were connected): the room
#: was reset and every client must rejoin.
WS_CLOSE_DOCUMENT_REPLACED = 4409

#: An empty Yjs update — what `Doc.get_update()` answers for an empty document
#: and what `handle_sync_message` already ignores.
EMPTY_UPDATE = b"\x00\x00"


def is_document_update(frame: bytes) -> bool:
    """Whether a y-websocket frame would CHANGE the document if applied: a sync
    step 2 or an update. Step 1 (a request for state) and awareness are not."""
    return (
        len(frame) >= 2
        and frame[0] == YMessageType.SYNC
        and frame[1] in (YSyncMessageType.SYNC_STEP2, YSyncMessageType.SYNC_UPDATE)
    )
