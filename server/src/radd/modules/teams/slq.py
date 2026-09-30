"""SLQ membership fields (RADD-1497): `reporter_team`, `assignee_team`.

A team is named by its (unique) name; membership is the roster's effective one —
direct rows plus the people a directory group carries, nesting included — through
`reading.member_projection`, so the query says what the Team page shows. Resolvers
are synchronous and get no session (the kernel contract), so everything here is a
nested `Select` the items compiler wraps as `work_items.id IN (…)`.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy import Select, false, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.kernel import SlqFieldContext, SlqFieldSpec

from . import reading, service
from .models import Team

#: How many names autocomplete offers for a partial.
SUGGEST_LIMIT = 20


def _team_ids(contains: bool, value: str) -> Select:
    condition = Team.name.ilike(ilike_term(value)) if contains else Team.name == value
    return select(Team.id).where(condition)


def _member_field(
    person_column: Callable[[], Any],
) -> Callable[[bool, str, SlqFieldContext], Select]:
    def item_ids(contains: bool, value: str, ctx: SlqFieldContext) -> Select:
        # Lazy: `items` loads after `teams` (a weak dependency), and its models
        # are spine reads.
        from radd.modules.items.models import WorkItem

        if ctx.is_me:
            # `reporter_team = me` has no meaning a person would expect (a team is
            # not a person); an empty result, never a guess.
            return select(WorkItem.id).where(false())
        members = reading.member_projection(_team_ids(contains, value)).subquery()
        return select(WorkItem.id).where(person_column().in_(select(members.c.user_id)))

    return item_ids


async def suggest_team_names(session: AsyncSession, partial: str) -> list[str]:
    return [
        team.name
        for team in await service.list_teams(session, q=partial or None, limit=SUGGEST_LIMIT)
    ]


def _lazy_column(name: str) -> Callable[[], Any]:
    def column() -> Any:
        from radd.modules.items.models import WorkItem

        return getattr(WorkItem, name)

    return column


SLQ_FIELDS: tuple[SlqFieldSpec, ...] = (
    SlqFieldSpec(
        name="reporter_team",
        label="Reporter's team",
        item_ids=_member_field(_lazy_column("reporter_id")),
        values="team name",
        suggest=suggest_team_names,
        reveals=("reporter",),
    ),
    SlqFieldSpec(
        name="assignee_team",
        label="Assignee's team",
        item_ids=_member_field(_lazy_column("assignee_id")),
        values="team name",
        suggest=suggest_team_names,
        reveals=("assignee",),
    ),
)
