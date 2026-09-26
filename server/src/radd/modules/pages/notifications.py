"""The wiki as a notification SUBJECT (RADD-1385; spec 118's page fan-out).

`notify` owns the mechanism — who is planned, the channel matrix, the inbox,
the mail — and asks this object, on the kernel `NOTIFICATION_SUBJECT` socket,
only what the wiki knows: where a page lives, who watches it, who may read it,
and which spaces a person may subscribe to. It used to reach into this module
for those answers through `try: import` guards that never fired (plugin code is
always importable), so a wiki switched off in the plugin manager was still
consulted. Registered on the manifest instead: disabling the plugin withdraws
the provider, and notify stops notifying about pages rather than asking a
switched-off module.

A page's visibility is a space role PLUS every restriction on the ancestor path
(RADD-948) — three layers notify would otherwise have to reimplement and keep in
step, which is why the read gate is answered here.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.choices import ChoiceRead
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.comments.types import CommentEvent
from radd.modules.events.service import Event
from radd.modules.notify.types import NotificationType, RuleScope, SubjectRef

from . import access, options, page_access, refs, service, watchers
from .models import Page
from .types import PageEntity, PageEvent


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def _payload(page: dict, space: dict) -> dict:
    """The stored notification payload for anything about a page.

    The keys RADD-719 wrote, and for its reason: an inbox row renders and links
    from the payload alone (`page_number` is the permalink, RADD-1233), resolved
    at write time, so a later rename cannot make the entry lie about what it told
    you at the time.
    """
    return {
        "page_id": page.get("id"),
        "page_number": page.get("number"),
        "page_slug": page.get("slug"),
        "space_slug": space.get("slug"),
        "title": page.get("title"),
        "version": page.get("version"),
    }


class PageNotificationSubject:
    """`NotificationSubjectProvider` for the entity type `page`."""

    entity_type = PageEntity.PAGE.value
    scope = RuleScope.SPACE.value
    events = {
        PageEvent.PAGE_CREATED.value: NotificationType.PAGE_CREATED.value,
        PageEvent.PAGE_UPDATED.value: NotificationType.PAGE_UPDATED.value,
    }

    async def locate(self, session: AsyncSession, event: Event) -> SubjectRef | None:
        """The page an event is about, with its space and display payload.

        A page event carries both refs (the kernel writes them from
        `emit(subjects=…)`), so what the row says is what was true at the edit.
        A comment names its page only as `entity_id` — `comments` is polymorphic
        — so that one is looked up; the page ref carries its space (RADD-1248).
        """
        payload = event.payload or {}
        if event.event_type == CommentEvent.CREATED.value:
            page_id = _uuid(payload.get("entity_id"))
            page = (await refs.page_ref(session, page_id) if page_id else None) or {}
            space = page.get("space") or {}
        else:
            page = payload.get(PageEntity.PAGE.value) or {}
            space = payload.get(PageEntity.SPACE.value) or {}
            page_id = _uuid(page.get("id")) or _uuid(event.entity_id)
        if page_id is None:
            return None
        return SubjectRef(id=page_id, scope_id=_uuid(space.get("id")), payload=_payload(page, space))

    async def watcher_ids(self, session: AsyncSession, subject_id: uuid.UUID) -> set[uuid.UUID]:
        return set(await watchers.watcher_ids(session, subject_id))

    async def reader_ids(
        self, session: AsyncSession, subject_id: uuid.UUID, user_ids
    ) -> set[uuid.UUID]:
        """Which of these ACTIVE people may read this page now.

        Batched per page rather than per person: one edit notifies a handful of
        watchers and the space permission lookup is the expensive part. A missing
        page reads as "nobody" — a notification about a page deleted between the
        edit and the fan-out has nothing to link to anyway.
        """
        wanted = list(user_ids)
        page = await session.get(Page, subject_id) if wanted else None
        if page is None:
            return set()
        users = await auth.users_by_ids(session, set(wanted))
        allowed: set[uuid.UUID] = set()
        for user_id in wanted:
            user: User | None = users.get(user_id)
            if user is None or not user.active:
                continue
            if await page_access.page_access(session, user, page):
                allowed.add(user_id)
        return allowed

    async def scope_options(
        self, session: AsyncSession, actor: User, *, q: str, limit: int, offset: int,
        exclude: list[str],
    ) -> tuple[list[ChoiceRead], int]:
        """The spaces a person may subscribe to — exactly `GET /page-spaces`'s set."""
        return await options.list_options(
            session, actor, q=q, limit=limit, offset=offset, exclude=exclude
        )

    async def scope_names(
        self, session: AsyncSession, actor: User, scope_ids
    ) -> dict[uuid.UUID, str]:
        """Of these spaces, the ones this actor may read, by name. Narrowed
        BEFORE the name query, so an unreadable space is never fetched."""
        readable = set(await access.readable_spaces(session, actor))
        return await service.space_names(session, set(scope_ids) & readable)


PAGE_NOTIFICATIONS = PageNotificationSubject()
