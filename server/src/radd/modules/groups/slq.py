"""SLQ membership fields (RADD-1497): `reporter_group`, `assignee_group`.

A directory group is named by its name or, since names are not unique across OUs,
by its distinguished name — a value with an `=` in it is read as a DN. Membership
is nested (`reading.member_projection`, depth-limited, cycle-safe), the way every
other reader of the mirror sees it. A person the directory never synced (a local
account) is in no group and matches nothing: that is the answer, not an error.
Resolvers are synchronous and get no session, so everything is a nested `Select`.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy import Select, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.kernel import SlqFieldContext, SlqFieldSpec

from . import reading, service
from .models import Group

#: How many names autocomplete offers for a partial.
SUGGEST_LIMIT = 20


def is_distinguished_name(value: str) -> bool:
    """`cn=pipeline-global,ou=groups,dc=…` rather than `pipeline-global`."""
    return "=" in value


def _group_ids(contains: bool, value: str) -> Select:
    if contains:
        needle = ilike_term(value)
        return select(Group.id).where(or_(Group.name.ilike(needle), Group.dn.ilike(needle)))
    if is_distinguished_name(value):
        return select(Group.id).where(Group.dn == value)
    return select(Group.id).where(Group.name == value)


def _member_field(
    person_column: Callable[[], Any],
) -> Callable[[bool, str, SlqFieldContext], Select]:
    def item_ids(contains: bool, value: str, ctx: SlqFieldContext) -> Select:
        from radd.modules.items.models import WorkItem  # spine read; items loads later

        if ctx.is_me:
            return select(WorkItem.id).where(false())
        members = reading.member_projection(_group_ids(contains, value)).subquery()
        return select(WorkItem.id).where(person_column().in_(select(members.c.user_id)))

    return item_ids


async def suggest_group_names(session: AsyncSession, partial: str) -> list[str]:
    names: list[str] = []
    for group in await service.list_groups(session, q=partial or None, limit=SUGGEST_LIMIT):
        if group.name not in names:
            names.append(group.name)
    return names


def _lazy_column(name: str) -> Callable[[], Any]:
    def column() -> Any:
        from radd.modules.items.models import WorkItem

        return getattr(WorkItem, name)

    return column


SLQ_FIELDS: tuple[SlqFieldSpec, ...] = (
    SlqFieldSpec(
        name="reporter_group",
        label="Reporter's directory group",
        item_ids=_member_field(_lazy_column("reporter_id")),
        values="group name or DN (nested membership)",
        suggest=suggest_group_names,
        reveals=("reporter",),
    ),
    SlqFieldSpec(
        name="assignee_group",
        label="Assignee's directory group",
        item_ids=_member_field(_lazy_column("assignee_id")),
        values="group name or DN (nested membership)",
        suggest=suggest_group_names,
        reveals=("assignee",),
    ),
)
