"""In-transaction hook points this module dispatches (spec 122).

The same inversion `items/hooks.py` made for spec 119: `pages` must never import
`collab` (collab depends on pages, and `tests/test_module_contracts.py` refuses
the cycle), so pages DISPATCHES around a body write and whoever holds the live
document REGISTERS. With no subscriber the dispatch is a no-op and a save is
byte-identical to what it was.

Two moments, named for the moment rather than the fact:

* `page.body_writing` — before the write. A handler may REFUSE it (raise
  `ConflictError`) or VOUCH for it (set `live_editor`), which is how a save
  that came from the room skips the `expected_version` check without the
  service knowing what a room is.
* `page.version_bumped` — after `version` moved, still inside the transaction.
  A handler that tracks the page's version (the room's stored CRDT state is
  tagged with one) learns the new number here; a handler that finds the body
  was replaced by something that was NOT its own session learns its copy is
  stale.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from .models import Page


class PageHook(StrEnum):
    BODY_WRITING = "page.body_writing"
    VERSION_BUMPED = "page.version_bumped"


@dataclass
class PageBodyWriting:
    """The subject of `PageHook.BODY_WRITING`. Mutable on purpose: `live_editor`
    is the handler's ANSWER, written back for the service to read."""

    page: Page
    actor_id: uuid.UUID
    collab_session: uuid.UUID | None
    #: Whether the save actually changes the body (a same-text save or a
    #: title-only save carrying `collab_session` changes nothing a room holds).
    body_changes: bool
    #: Set by a handler when `collab_session` names a connected editor of this
    #: page's live document — the save came FROM the room.
    live_editor: bool = False


@dataclass(frozen=True)
class PageVersionBumped:
    """The subject of `PageHook.VERSION_BUMPED`: `page.version` is already the
    new number."""

    page: Page
    collab_session: uuid.UUID | None
    body_changed: bool
    live_editor: bool
