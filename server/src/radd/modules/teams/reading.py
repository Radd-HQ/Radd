"""Team roster windows over effective direct and directory-group membership."""
import uuid

from sqlalchemy import case, func, null, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.modules.auth.models import User
from radd.modules.auth.types import UserSource
from radd.modules.groups import service as groups
from .models import Team, TeamMember, TeamManager
from .schemas import TeamMemberRead, TeamPersonChoice, TeamStewardPerson, TeamStewardshipRead, TeamGroupRead, TeamGroupChoice


def member_projection(team_id: uuid.UUID):
    roots = select(TeamMember.group_id).where(TeamMember.team_id == team_id,
                                             TeamMember.group_id.is_not(None))
    inherited = groups.member_projection(roots).subquery()
    people = union_all(
        select(TeamMember.user_id, null().label("via_group")).where(
            TeamMember.team_id == team_id, TeamMember.user_id.is_not(None)),
        select(inherited.c.user_id, groups.Group.name.label("via_group"))
        .join(groups.Group, groups.Group.id == inherited.c.root_id),
    ).subquery()
    # A direct row wins. Otherwise name ordering chooses a stable carrier when
    # several groups reach the same person, matching the former sorted loop.
    return select(people.c.user_id, case(
        (func.bool_or(people.c.via_group.is_(None)), None),
        else_=func.min(people.c.via_group)).label("via_group")
    ).group_by(people.c.user_id)


def _filter(query, q: str):
    if q.strip():
        term = ilike_term(q.strip())
        query = query.where(User.name.ilike(term) | User.email.ilike(term))
    return query


async def member_page(session: AsyncSession, team_id: uuid.UUID, *, q: str = "",
                      limit: int | None = None, offset: int = 0):
    members = member_projection(team_id).subquery()
    query = _filter(select(User.id.label("user_id"), User.name, User.email, members.c.via_group)
                    .join(members, members.c.user_id == User.id), q)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(User.name, User.id)
    if limit is not None:
        query = query.limit(limit).offset(offset)
    rows = (await session.execute(query)).mappings()
    return [TeamMemberRead.model_validate(row) for row in rows], total or 0


async def candidate_page(session: AsyncSession, team_id: uuid.UUID, *, q: str = "",
                         limit: int = 50, offset: int = 0):
    members = member_projection(team_id).subquery()
    # Match the public-directory add-member vocabulary: active people/service
    # accounts, no mail-provisioned requesters. Exclude the ENTIRE effective
    # roster before search/count/paging; expose no administrative user fields.
    query = _filter(select(User.id, User.name).where(
        User.active.is_(True), User.source != UserSource.EMAIL,
        ~User.id.in_(select(members.c.user_id))), q)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(User.name, User.id).limit(limit).offset(offset))).mappings()
    return [TeamPersonChoice.model_validate(row) for row in rows], total or 0


async def stewardship_page(session: AsyncSession, team: Team, *, limit: int = 50,
                           offset: int = 0) -> TeamStewardshipRead:
    owner = (await session.execute(select(User.id, User.name, User.active)
                                   .where(User.id == team.owner_id))).mappings().first()
    query = select(User.id, User.name, User.active).join(TeamManager, TeamManager.user_id == User.id).where(
        TeamManager.team_id == team.id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(User.name, User.id).limit(limit).offset(offset))).mappings()
    return TeamStewardshipRead(owner=TeamStewardPerson.model_validate(owner) if owner else None,
                              managers=[TeamStewardPerson.model_validate(row) for row in rows], total=total or 0)


async def steward_candidates(session: AsyncSession, team: Team, *, purpose: str,
                             q: str = "", limit: int = 50, offset: int = 0):
    query = select(User.id, User.name).where(User.active.is_(True), User.source != UserSource.EMAIL)
    if team.owner_id:
        query = query.where(User.id != team.owner_id)
    if purpose == "manager":
        query = query.where(~User.id.in_(select(TeamManager.user_id).where(TeamManager.team_id == team.id)))
    # Existing managers may be promoted to owner. Saved inactive people remain
    # named in stewardship_page, independently of eligible candidate search.
    query = _filter(query, q)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(User.name, User.id).limit(limit).offset(offset))).mappings()
    return [TeamPersonChoice.model_validate(row) for row in rows], total or 0


async def group_page(session: AsyncSession, team_id: uuid.UUID, *, candidates: bool = False,
                     q: str = "", limit: int | None = None, offset: int = 0):
    group = groups.Group
    held = select(TeamMember.group_id).where(TeamMember.team_id == team_id, TeamMember.group_id.is_not(None))
    query = select(group.id.label("group_id"), group.name, group.dn, group.directory_missing_since).where(
        ~group.id.in_(held) if candidates else group.id.in_(held))
    if q.strip():
        term = ilike_term(q.strip())
        query = query.where(group.name.ilike(term) | group.dn.ilike(term))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(group.name, group.id)
    if limit is not None:
        query = query.limit(limit).offset(offset)
    rows = list((await session.execute(query)).mappings())
    if not candidates:
        return [TeamGroupRead.model_validate(row) for row in rows], total or 0
    ids = [row["group_id"] for row in rows]
    direct = await groups.direct_member_counts(session, ids)
    transitive = await groups.transitive_member_counts(session, ids)
    return [TeamGroupChoice(**row, direct_member_count=direct.get(row["group_id"], 0),
                            transitive_member_count=transitive.get(row["group_id"], 0)) for row in rows], total or 0


async def member_counts(session: AsyncSession, team_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """One effective-membership projection for a requested team window.

    Deduplicate (team, user), including overlaps across direct membership,
    multiple attached roots and nested-group diamonds/cycles.
    """
    if not team_ids:
        return {}
    roots = select(TeamMember.group_id).where(
        TeamMember.team_id.in_(team_ids), TeamMember.group_id.is_not(None),
    )
    inherited = groups.member_projection(roots).subquery()
    members = select(TeamMember.team_id, TeamMember.user_id).where(
        TeamMember.team_id.in_(team_ids), TeamMember.user_id.is_not(None),
    ).union(
        select(TeamMember.team_id, inherited.c.user_id).join(
            inherited, inherited.c.root_id == TeamMember.group_id,
        ).where(TeamMember.team_id.in_(team_ids)),
    ).subquery()
    rows = await session.execute(select(members.c.team_id, func.count()).select_from(members)
        .join(User, User.id == members.c.user_id).group_by(members.c.team_id))
    return dict(rows.all())
