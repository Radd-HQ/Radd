"""In-transaction hook points around a page body write (spec 122). `pages`
dispatches and never imports `collab` (collab depends on pages); with no
subscriber a save is unchanged.

* `page.body_writing` — before the write; a handler may REFUSE it (ConflictError)
  or VOUCH for it (`live_editor`), which skips `expected_version`.
* `page.version_bumped` — after `version` moved; the room re-tags its state, or
  learns that a write from elsewhere made its copy stale.
* `page.body_autosaved` — a live autosave inside the history window: body saved,
  version not bumped; the session owes a seal (RADD-1244).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from .models import Page


class PageHook(StrEnum):
    BODY_WRITING = "page.body_writing"
    VERSION_BUMPED = "page.version_bumped"
    #: RADD-1244: see the module docstring.
    BODY_AUTOSAVED = "page.body_autosaved"


@dataclass
class PageBodyWriting:
    """The subject of `PageHook.BODY_WRITING`. Mutable on purpose: `live_editor`
    is the handler's ANSWER, written back for the service to read."""

    page: Page
    actor_id: uuid.UUID
    collab_session: uuid.UUID | None
    #: Whether the body actually changes (a title-only save touches nothing a room holds).
    body_changes: bool
    #: Set by a handler when `collab_session` names a connected editor: the save came FROM the room.
    live_editor: bool = False


@dataclass(frozen=True)
class PageBodyAutosaved:
    """The subject of `PageHook.BODY_AUTOSAVED`: the body is saved, the
    version is NOT bumped, and no history row exists for this content yet."""

    page: Page


@dataclass(frozen=True)
class PageVersionBumped:
    """The subject of `PageHook.VERSION_BUMPED`: `page.version` is already the
    new number."""

    page: Page
    collab_session: uuid.UUID | None
    body_changed: bool
    live_editor: bool
