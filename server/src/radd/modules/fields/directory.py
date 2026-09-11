"""Lean field settings reads using the same scope ladder as field mutations."""

import uuid
from dataclasses import dataclass

from sqlalchemy import String, case, cast, exists, false, func, literal, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from radd import choices
from radd.exceptions import NotFoundError
from radd.db import ilike_term
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.projects.models import Project

from . import service
from .models import FieldDefinition, FieldProject
from .schemas import FieldManagementRead, FieldSettingsSummaryRead, FieldSummaryRead
from .types import FieldEntity

FIELD_SETTINGS_PERMISSIONS = (
    authz.Permission.FIELD_CREATE,
    authz.Permission.FIELD_UPDATE,
    authz.Permission.FIELD_DELETE,
    authz.Permission.FIELD_MANAGE,
)


@dataclass
class Policy:
    global_permissions: frozenset[authz.Permission]
    projects: dict[uuid.UUID, frozenset[authz.Permission]]
    member: bool

    def holds(self, permission: authz.Permission, ids: list[uuid.UUID]) -> bool:
        if not ids:
            return authz.holds_base(self.global_permissions, permission)
        return all(authz.holds_base(self.projects.get(pid, frozenset()), permission) for pid in ids)

    def projects_holding(self, permission: authz.Permission) -> list[uuid.UUID]:
        return [pid for pid, perms in self.projects.items() if authz.holds_base(perms, permission)]

    def readable(self):
        # Preserve the legacy issue-member registry floor; additionally admit
        # definitions whose entire scope this actor can administer/read.
        if self.member or any(self.holds(p, []) for p in FIELD_SETTINGS_PERMISSIONS):
            return true()
        scoped = exists().where(FieldProject.field_id == FieldDefinition.id)
        conditions = []
        for permission in FIELD_SETTINGS_PERMISSIONS:
            permitted = self.projects_holding(permission)
            if permitted:
                outside = exists().where(
                    FieldProject.field_id == FieldDefinition.id,
                    FieldProject.project_id.not_in(permitted),
                )
                conditions.append(scoped & ~outside)
        return or_(*conditions) if conditions else false()


async def policy(session: AsyncSession, actor: User) -> Policy:
    return Policy(
        await authz.effective_permissions(session, actor),
        await authz.project_permission_map(session, actor),
        bool(await authz.readable_projects(session, actor)),
    )


async def summary(session: AsyncSession, actor: User) -> FieldSettingsSummaryRead:
    permissions = await policy(session, actor)
    return FieldSettingsSummaryRead(
        can_access=any(
            permissions.holds(p, []) or permissions.projects_holding(p)
            for p in FIELD_SETTINGS_PERMISSIONS
        ),
        can_create=bool(
            permissions.holds(authz.Permission.FIELD_CREATE, [])
            or permissions.projects_holding(authz.Permission.FIELD_CREATE)
        ),
        can_create_global=permissions.holds(authz.Permission.FIELD_CREATE, []),
        can_update_global=permissions.holds(authz.Permission.FIELD_UPDATE, []),
        can_manage_builtin=permissions.holds(authz.Permission.FIELD_MANAGE, []),
        can_manage_builtin_projects=bool(permissions.projects_holding(authz.Permission.FIELD_MANAGE)),
    )


async def page(
    session: AsyncSession, actor: User, *, q: str = "", limit: int = 50, offset: int = 0
) -> tuple[list[FieldSummaryRead], int]:
    permissions = await policy(session, actor)
    condition = permissions.readable()
    if q.strip():
        term = ilike_term(q.strip())
        condition &= or_(FieldDefinition.name.ilike(term), FieldDefinition.key.ilike(term))
    total = await session.scalar(select(func.count()).select_from(FieldDefinition).where(condition))
    project_count = (
        select(func.count())
        .select_from(FieldProject)
        .where(FieldProject.field_id == FieldDefinition.id)
        .scalar_subquery()
    )
    rows = list(
        (
            await session.execute(
                select(
                    FieldDefinition.id,
                    FieldDefinition.key,
                    FieldDefinition.name,
                    FieldDefinition.type,
                    project_count.label("project_count"),
                )
                .where(condition)
                .order_by(FieldDefinition.created_at, FieldDefinition.id)
                .limit(limit)
                .offset(offset)
            )
        ).mappings()
    )
    restricted = await service.restricted_field_ids(session, ids=[str(row["id"]) for row in rows])
    return [
        FieldSummaryRead(**row, restricted=str(row["id"]) in restricted) for row in rows
    ], total or 0


def _options_array():
    # Historical non-select definitions may contain SQL NULL or JSON null.
    return case(
        (func.jsonb_typeof(FieldDefinition.options) == "array", FieldDefinition.options),
        else_=literal([], type_=JSONB),
    )


async def by_id(
    session: AsyncSession, actor: User, identifier: uuid.UUID, *, include_options: bool = True
) -> FieldManagementRead:
    permissions = await policy(session, actor)
    columns = [c for c in FieldDefinition.__table__.columns if c.name != "options"]
    row = (await session.execute(
        select(
            *columns,
            (FieldDefinition.options if include_options else literal(None, type_=JSONB)).label("options"),
            func.jsonb_array_length(_options_array()).label("option_count"),
        ).where(
            FieldDefinition.id == identifier,
            permissions.readable(),
        )
    )).mappings().one_or_none()
    if row is None:
        raise NotFoundError(FieldEntity.FIELD, identifier)
    project_ids = list(await session.scalars(
        select(FieldProject.project_id).where(FieldProject.field_id == identifier)
        .order_by(FieldProject.project_id)
    ))
    restricted = await service.restricted_field_ids(session, ids=[str(identifier)])
    read = FieldManagementRead(**row, project_ids=project_ids)
    return read.model_copy(
        update={
            "restricted": str(identifier) in restricted,
            "can_update": permissions.holds(authz.Permission.FIELD_UPDATE, project_ids),
            "can_delete": permissions.holds(authz.Permission.FIELD_DELETE, project_ids),
            "can_manage": permissions.holds(authz.Permission.FIELD_MANAGE, project_ids),
        }
    )


async def option_page(
    session: AsyncSession, actor: User, identifier: uuid.UUID, *, q: str = "",
    exclude: str | None = None, limit: int = 50, offset: int = 0,
) -> tuple[list[str], int]:
    permissions = await policy(session, actor)
    allowed = select(FieldDefinition.id).where(
        FieldDefinition.id == identifier, permissions.readable(),
    )
    if await session.scalar(allowed) is None:
        raise NotFoundError(FieldEntity.FIELD, identifier)
    # Expand in PostgreSQL: only the requested window crosses the driver boundary.
    options = func.jsonb_array_elements_text(_options_array()).table_valued(
        "value", with_ordinality="position",
    ).render_derived()
    projection = select(options.c.value, options.c.position).select_from(
        FieldDefinition.__table__.join(options, true())
    ).where(FieldDefinition.id == identifier, permissions.readable())
    if q.strip():
        projection = projection.where(options.c.value.ilike(ilike_term(q.strip())))
    if exclude is not None:
        projection = projection.where(options.c.value != exclude)
    total = await session.scalar(select(func.count()).select_from(projection.subquery()))
    rows = await session.scalars(projection.order_by(options.c.position).limit(limit).offset(offset))
    return list(rows), total or 0


async def project_choices(
    session: AsyncSession,
    actor: User,
    permission: authz.Permission,
    *,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
):
    permissions = await policy(session, actor)
    projection = select(
        cast(Project.id, String).label("value"),
        Project.key.label("label"),
        Project.name.label("hint"),
    ).where(Project.id.in_(permissions.projects_holding(permission)))
    return await choices.page(session, projection, q=q, limit=limit, offset=offset)


async def project_references(session: AsyncSession, actor: User, ids: list[uuid.UUID]):
    # Existing scope labels may be readable through issue access OR field
    # authority. A field administrator need not be able to read issue content.
    permissions = await policy(session, actor)
    allowed = set(await authz.visible_projects(session, actor))
    for permission in FIELD_SETTINGS_PERMISSIONS:
        allowed.update(permissions.projects_holding(permission))
    rows = await session.execute(
        select(
            cast(Project.id, String).label("value"),
            Project.key.label("label"),
            Project.name.label("hint"),
        )
        .where(Project.id.in_(ids), Project.id.in_(allowed))
        .order_by(Project.key, Project.id)
    )
    return [choices.ChoiceRead.model_validate(row) for row in rows.mappings()]
