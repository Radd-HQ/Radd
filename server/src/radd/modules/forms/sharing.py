"""Bounded portal share management; legacy replacement shares the same row lock."""
import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.choices import page as choice_page
from radd.db import ilike_term
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import NON_PERSON_SOURCES
from radd.modules.projects import service as projects
from radd.modules.teams.models import Team

from .models import Form, FormShare
from .schemas import FormShareDirectoryRead, FormShareEntry, FormShareRead
from .types import FormEntity, FormEvent, FormShareSubject


async def managed_form(session: AsyncSession, form_id: uuid.UUID, actor: User, *, lock: bool = False):
    from .service import get_form
    form = await get_form(session, form_id)
    project = await projects.get_project(session, form.project_id)
    await authz.require(session, actor, authz.Permission.FORM_MANAGE, project=project)
    if lock:
        form = await session.scalar(select(Form).where(Form.id == form_id).with_for_update())
        if form is None:
            raise NotFoundError(FormEntity.FORM, form_id)
    return form, project


async def directory(session: AsyncSession, form_id: uuid.UUID, actor: User, *, q: str = "", limit: int = 50, offset: int = 0):
    await managed_form(session, form_id, actor)
    can_read_teams = await authz.holds(session, actor, authz.Permission.TEAM_READ)
    # A portal grant does not grant its manager access to hidden subject catalogs.
    name = case(
        (User.source.notin_(NON_PERSON_SOURCES), User.name),
        (FormShare.team_id.is_not(None) & can_read_teams, Team.name),
        else_=None,
    ).label("subject_name")
    active = case((User.source.notin_(NON_PERSON_SOURCES), User.active), else_=None).label("active")
    query = select(FormShare, name, active).outerjoin(User, User.id == FormShare.user_id).outerjoin(Team, Team.id == FormShare.team_id).where(FormShare.form_id == form_id)
    if q.strip():
        query = query.where(name.ilike(ilike_term(q.strip())))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(query.order_by(FormShare.created_at, FormShare.id).limit(limit).offset(offset))
    return [FormShareDirectoryRead(**FormShareRead.model_validate(row).model_dump(), subject_name=label, active=enabled)
            for row, label, enabled in rows], total or 0


async def candidates(session: AsyncSession, form_id: uuid.UUID, actor: User, kind: FormShareSubject, *, q: str = "", limit: int = 50, offset: int = 0):
    from sqlalchemy import String, cast, literal
    await managed_form(session, form_id, actor)
    if kind == FormShareSubject.USER:
        held = select(FormShare.user_id).where(FormShare.form_id == form_id, FormShare.user_id.is_not(None))
        query = select(cast(User.id, String).label("value"), User.name.label("label"), literal("").label("hint")).where(User.active, User.source.notin_(NON_PERSON_SOURCES), ~User.id.in_(held))
    else:
        if not await authz.holds(session, actor, authz.Permission.TEAM_READ):
            return [], 0
        held = select(FormShare.team_id).where(FormShare.form_id == form_id, FormShare.team_id.is_not(None))
        query = select(cast(Team.id, String).label("value"), Team.name.label("label"), literal("").label("hint")).where(~Team.id.in_(held))
    rows, total = await choice_page(session, query, q=q, limit=limit, offset=offset)
    return rows, total


async def add(session: AsyncSession, form_id: uuid.UUID, data: FormShareEntry, actor: User) -> FormShareRead:
    from .service import _emit, _validate_share_subjects
    form, project = await managed_form(session, form_id, actor, lock=True)
    await _validate_share_subjects(session, [data])
    subject = FormShare.user_id == data.user_id if data.user_id else FormShare.team_id == data.team_id
    existing = await session.scalar(select(FormShare.id).where(FormShare.form_id == form_id, subject))
    if existing is not None:
        raise ConflictError(FormEntity.FORM, reason="that portal share already exists")
    row = FormShare(form_id=form_id, user_id=data.user_id, team_id=data.team_id)
    session.add(row)
    await session.flush()
    count = await session.scalar(select(func.count()).select_from(FormShare).where(FormShare.form_id == form_id))
    await _emit(session, FormEvent.UPDATED, form, project, actor, extra={"share_count": count})
    return FormShareRead.model_validate(row)


async def remove(session: AsyncSession, form_id: uuid.UUID, share_id: uuid.UUID, actor: User) -> None:
    from .service import _emit
    form, project = await managed_form(session, form_id, actor, lock=True)
    row = await session.scalar(select(FormShare).where(FormShare.form_id == form_id, FormShare.id == share_id))
    if row is None:
        raise NotFoundError(FormEntity.FORM, share_id)
    await session.delete(row)
    await session.flush()
    count = await session.scalar(select(func.count()).select_from(FormShare).where(FormShare.form_id == form_id))
    await _emit(session, FormEvent.UPDATED, form, project, actor, extra={"share_count": count})
