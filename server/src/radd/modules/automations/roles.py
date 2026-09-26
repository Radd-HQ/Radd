"""Person params: an email address, or a `PersonRole` resolved on the target
item — which is why a role forces per-item arity (RADD-918). Contributed
actions read the same grammar through `ctx.person`."""

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
    """Whether a person param names a ROLE (resolves on one item) not an address."""
    try:
        PersonRole(value.strip().lower())
    except ValueError:
        return False
    return True


def resolve_user(role: str, item: WorkItem | None) -> uuid.UUID | None:
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
        user_id = resolve_user(value, item)
        return None if user_id is None else Person(user_id, value.strip().lower())
    user = await auth_service.get_user_by_email(session, value.strip())
    return None if user is None else Person(user.id, value.strip())
