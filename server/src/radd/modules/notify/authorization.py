"""Revalidate queued delivery against current resource and discussion access."""

import uuid

from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.auth.authz import Permission
from radd.modules.comments.reading import can_read_comment
from radd.modules.items.service import require_readable_item
from radd.modules.pages.page_access import guard_page


async def notification_readable(session, notification, user) -> bool:
    # A queued row records historical eligibility, not a lasting access grant.
    try:
        if notification.item_id is not None:
            await require_readable_item(session, notification.item_id, user)
        elif (notification.payload or {}).get("page_id"):
            await guard_page(
                session, user, uuid.UUID(notification.payload["page_id"]), Permission.PAGE_READ
            )
        else:
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
