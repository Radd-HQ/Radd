"""Wire vocabulary for the collab module (spec 122)."""

from enum import IntEnum, StrEnum

from pycrdt import YMessageType, YSyncMessageType

from radd.modules.auth.types import Permission


class CollabRole(StrEnum):
    """What a session may do to the live document. An observer's awareness
    (cursor, name) is relayed; its document updates are dropped at the seam."""

    EDITOR = "editor"
    OBSERVER = "observer"

    @property
    def permission(self) -> Permission:
        """The page atom this role is joined, and re-checked, against."""
        return Permission.PAGE_WRITE if self is CollabRole.EDITOR else Permission.PAGE_READ


#: This module's id in the kernel registry — the plugin's `name`.
PLUGIN_ID = "collab"

#: WebSocket close codes (4000-range). 4401 is numerically the realtime
#: module's, so a client has one meaning for it.
WS_CLOSE_UNAUTHENTICATED = 4401
#: `session` missing, unknown, for another user/page, or its room is gone —
#: the client must `POST …/join` again.
WS_CLOSE_SESSION_UNKNOWN = 4403
#: The body was replaced by a write not from this room (an import, an MCP
#: update while only observers were connected): every client must rejoin.
WS_CLOSE_DOCUMENT_REPLACED = 4409

#: An empty Yjs update — what `Doc.get_update()` answers for an empty document
#: and what `handle_sync_message` already ignores.
EMPTY_UPDATE = b"\x00\x00"


class YClientMessage(IntEnum):
    """Client y-websocket messages pycrdt's `YMessageType` does not name. A
    provider asks for every awareness state on connect; silence leaves the
    newcomer alone until the next heartbeat (two savers for 15 s)."""

    QUERY_AWARENESS = 3


def is_awareness_query(frame: bytes) -> bool:
    return len(frame) >= 1 and frame[0] == YClientMessage.QUERY_AWARENESS


def is_document_update(frame: bytes) -> bool:
    """Whether a y-websocket frame would CHANGE the document if applied: a sync
    step 2 or an update. Step 1 (a request for state) and awareness are not."""
    return (
        len(frame) >= 2
        and frame[0] == YMessageType.SYNC
        and frame[1] in (YSyncMessageType.SYNC_STEP2, YSyncMessageType.SYNC_UPDATE)
    )
