"""Turning mention CANDIDATES into real recipients.

`planner.parse_mention_candidates` is pure and deliberately credulous — it hands
back every uuid and every @-address the text contains, valid or not. This is the
half that needs a database: resolving those candidates to accounts that exist and
are active.

Its own file because both halves of the consumer need it (an issue comment and,
since spec 118, a page comment) and neither should have to import the other to
get at it.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import service as auth
from radd.modules.events.service import Event

from . import planner


async def resolve_mentions(session: AsyncSession, text: str) -> frozenset[uuid.UUID]:
    """Mention candidates in `text` resolved to real, active users."""
    id_strings, emails = planner.parse_mention_candidates(text)
    resolved: set[uuid.UUID] = set()
    candidate_ids = set()
    for value in id_strings:
        try:
            candidate_ids.add(uuid.UUID(value))
        except ValueError:
            continue
    users = await auth.users_by_ids(session, candidate_ids)
    resolved.update(user_id for user_id, user in users.items() if user.active)
    for email in emails:
        user = await auth.get_user_by_email(session, email)
        if user is not None and user.active:
            resolved.add(user.id)
    return frozenset(resolved)


async def comment_mentions(
    session: AsyncSession, event: Event, payload: dict
) -> frozenset[uuid.UUID]:
    """Who a comment names. The event's excerpt is CAPPED, so the full body comes
    back through the comments seam — a mention past 200 characters is still a
    mention."""
    from radd.modules.comments import service as comments

    body = await comments.comment_body(session, uuid.UUID(event.entity_id))
    return await resolve_mentions(session, body or payload.get("excerpt", ""))
