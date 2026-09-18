"""The page hook handlers (spec 122): nothing publishes over live work.

Registered here rather than reached for by `pages`, because the dependency has
exactly one legal direction: `collab` depends on `pages`, so it is the side
that knows both names (the `automations/subscribers.py` shape).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.hooks import hooks
from radd.kernel.registry import registries
from radd.modules.auth import service as auth
from radd.modules.pages.hooks import PageBodyAutosaved, PageBodyWriting, PageHook, PageVersionBumped
from radd.modules.pages.types import PageEntity

from .rooms import hub
from .types import PLUGIN_ID


def is_enabled() -> bool:
    """Whether this module is still MOUNTED. `HookRegistry.on()` appends and
    nothing takes it back, so a hot-disabled plugin would go on refusing saves
    from a handler nobody can unregister — asked of the kernel registry, the
    same way `automations.subscribers.is_enabled` asks."""
    return PLUGIN_ID in registries.plugins


@hooks.on(PageHook.BODY_WRITING)
async def guard_live_document(session: AsyncSession, subject: PageBodyWriting) -> None:
    """While the page has a connected editor, a body write is either FROM the
    room (vouched for: `live_editor`) or refused, naming who is editing."""
    if not is_enabled():
        return
    editors = hub.live_editors(subject.page.id)
    if not editors:
        return
    if subject.collab_session is not None and any(
        editor.id == subject.collab_session for editor in editors
    ):
        subject.live_editor = True
        return
    if not subject.body_changes:
        return  # a title or a move touches nothing the room holds
    users = await auth.users_by_ids(session, {editor.user_id for editor in editors})
    names = sorted({user.name or user.email for user in users.values()})
    raise ConflictError(PageEntity.PAGE, reason=f"being edited live by {', '.join(names)}")


@hooks.on(PageHook.BODY_AUTOSAVED)
async def remember_unsealed(session: AsyncSession, subject: PageBodyAutosaved) -> None:
    """A live autosave inside the history window: the body moved, the version
    did not. The room owes a seal if the session ends without a final save."""
    del session
    if is_enabled():
        hub.mark_unsealed(subject.page.id)


@hooks.on(PageHook.VERSION_BUMPED)
async def follow_version(session: AsyncSession, subject: PageVersionBumped) -> None:
    """A save from the room moves the version the room's state is tagged with;
    a body written by anything else makes the room's copy stale, so it goes."""
    del session
    if not is_enabled():
        return
    if subject.body_changed and not subject.live_editor:
        await hub.invalidate(subject.page.id)
    else:
        hub.track_version(subject.page.id, subject.page.version)
