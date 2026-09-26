"""Person params: an email address, or a `PersonRole` on the target item.

`notify_user` and `add_watcher` take a person as either a literal email or a
role (`reporter`/`assignee`) resolved against ONE item — which is why a role
forces per-item arity (RADD-918). A contributed action reads the same grammar
through `ctx.person` (RADD-1387), so `participants`' Add participant resolves a
person exactly as the built-ins do without importing this module.

Until RADD-1387 this file was `email_action.py` and also held the send_email
action's recipient resolution — which meant importing `mailintake` and
`participants` behind `settings.modules` checks. `settings.modules` is BOOT
config, so a plugin disabled at runtime kept being called. The email action
and its `contact` role now live in `mailintake`; this is what is left, and it
is automations' own grammar.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import service as auth_service
from radd.modules.items.models import WorkItem

from .types import PersonRole


@dataclass(frozen=True)
class Person:
    """A resolved person param: who, and the words that named them (the role or
    the address) for the dry run's detail line."""

    user_id: uuid.UUID
    named_as: str


def is_role(value: str) -> bool:
    """Whether a person param names a ROLE rather than an address.

    Public because arity depends on it (RADD-918): a role resolves against ONE
    item, so an action addressed to `reporter` only means anything per item. The
    editor forces per-item mode when a role is chosen instead of letting someone
    build the version that skip-logs on every multi-item run.
    """
    try:
        PersonRole(value.strip().lower())
    except ValueError:
        return False
    return True


async def resolve_user(
    session: AsyncSession, role: str, item: WorkItem | None
) -> uuid.UUID | None:
    """The USER a role names on `item`, or None (no item, or nobody in it)."""
    if item is None:
        return None
    match role.strip().lower():
        case PersonRole.REPORTER:
            return item.reporter_id
        case PersonRole.ASSIGNEE:
            return item.assignee_id
    return None


async def resolve_person(
    session: AsyncSession, value: str, item: WorkItem | None
) -> Person | None:
    """A person param — already RENDERED if it was a template — as a user.

    A role resolves on `item`; anything else is looked up as an email. None
    means nobody: the caller skip-logs with its own verb in the sentence.
    """
    if is_role(value):
        user_id = await resolve_user(session, value, item)
        return None if user_id is None else Person(user_id, value.strip().lower())
    user = await auth_service.get_user_by_email(session, value.strip())
    return None if user is None else Person(user.id, value.strip())
