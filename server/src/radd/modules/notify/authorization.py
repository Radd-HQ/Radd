"""Revalidate queued delivery against current resource and discussion access."""

from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.comments.reading import can_read_comment
from radd.modules.items.service import require_readable_item

from . import subjects


async def notification_readable(session, notification, user) -> bool:
    # A queued row records historical eligibility, not a lasting access grant.
    try:
        if notification.item_id is not None:
            await require_readable_item(session, notification.item_id, user)
        elif not await subjects.readable(session, notification.payload or {}, user):
            # RADD-1385: a non-item subject answers through its provider — or,
            # its plugin disabled, nobody does and the row is not delivered.
            return False
        from .mailer import _comment_id

        comment_id = await _comment_id(session, notification)
        if comment_id is not None:
            return await can_read_comment(session, comment_id, user)
        if notification.event_id is not None:
            from radd.modules.events import service as events

            if await events.get_event(session, notification.event_id) is None:
                return False
        return True
    except (ForbiddenError, NotFoundError, ValueError, TypeError):
        return False
