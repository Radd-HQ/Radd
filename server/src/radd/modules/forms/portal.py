"""Requester portal (spec 73): the intake-form directory for signed-in users.

Eligibility = the form is ENABLED and (allow_public OR a `form_shares` row
matches the actor directly or one of their teams). The share IS the grant —
exactly the public-form trust model, so submits run as the SYSTEM actor with
`reporter_id=actor.id` (a known user: no mail-contact/ack path). Managing the
share list lives in service.update_sharing (`form.manage`); everything here is
for eligible visitors, and an ineligible/unknown/disabled form is one 404 — a
form you can't use might as well not exist.
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.modules.teams import service as teams_service
from radd.modules.projects import service as projects_service

from . import public, service
from .models import Form, FormShare
from .schemas import (
    FormSubmit,
    PortalFormCard,
    PortalFormRead,
    PortalGroup,
    PortalProjectRef,
    PortalRequestRead,
    PublicSubmitResult,
)
from .types import FormEntity


def _shared_form_ids(actor: User, team_ids: set[uuid.UUID]):
    """Subquery: form ids a share row grants to the actor or their teams."""
    return select(FormShare.form_id).where(
        or_(FormShare.user_id == actor.id, FormShare.team_id.in_(team_ids))
    )


async def _eligible_form(session: AsyncSession, form_id: uuid.UUID, actor: User) -> Form:
    form = await session.get(Form, form_id)
    if form is not None and form.enabled:
        if form.allow_public:
            return form
        team_ids = await teams_service.user_team_ids(session, actor.id)
        share = await session.scalar(
            select(FormShare.id)
            .where(FormShare.form_id == form.id)
            .where(or_(FormShare.user_id == actor.id, FormShare.team_id.in_(team_ids)))
            .limit(1)
        )
        if share is not None:
            return form
    raise NotFoundError(FormEntity.FORM, form_id)


async def list_portal_forms(session: AsyncSession, actor: User) -> list[PortalGroup]:
    """The directory: enabled forms across ALL projects the actor may use,
    grouped by project. Listing is by ELIGIBILITY, not membership (spec 73) —
    trimmed cards only, no tokens and no field config."""
    team_ids = await teams_service.user_team_ids(session, actor.id)
    result = await session.execute(
        select(Form)
        .where(Form.enabled.is_(True))
        .where(or_(Form.allow_public.is_(True), Form.id.in_(_shared_form_ids(actor, team_ids))))
        .order_by(Form.name, Form.id)
    )
    by_project: dict[uuid.UUID, list[Form]] = {}
    for form in result.scalars():
        by_project.setdefault(form.project_id, []).append(form)
    groups: list[PortalGroup] = []
    for project_id, forms in by_project.items():
        project = await projects_service.get_project(session, project_id)
        groups.append(
            PortalGroup(
                project=PortalProjectRef(id=project.id, key=project.key, name=project.name),
                forms=[
                    PortalFormCard(id=form.id, name=form.name, description=form.description)
                    for form in forms
                ],
            )
        )
    groups.sort(key=lambda group: (group.project.name.lower(), group.project.key))
    return groups


async def render_portal_form(
    session: AsyncSession, form_id: uuid.UUID, actor: User
) -> PortalFormRead:
    """Render payload for an ELIGIBLE actor: the spec-62 public trimming (the
    visitor may not read the registry) plus the form id + project ref."""
    form = await _eligible_form(session, form_id, actor)
    project = await projects_service.get_project(session, form.project_id)
    base = await public.trimmed_read(session, form)
    return PortalFormRead(
        id=form.id,
        project=PortalProjectRef(id=project.id, key=project.key, name=project.name),
        **base.model_dump(),
    )


async def list_my_requests(
    session: AsyncSession, actor: User, limit: int = 50
) -> list[PortalRequestRead]:
    """What this person has filed (RADD-785).

    Scoped by RELATIONSHIP, not by permission: the filter is
    `reporter_id == actor.id` and no `item.read` is asked of anyone. That is the
    same trust the submit path already extends — your own request is yours to
    see — and it is why a requester can be given a Baseline with no read at all
    and still track what they raised.

    Reaching into `work_items` from here is the tolerated inward read this
    module already does for submits; the trimming lives in `PortalRequestRead`,
    which carries no description, comments, assignee or fields. Being the
    reporter must not become a back door into an issue's contents.
    """
    from radd.modules.items.models import WorkItem
    from radd.modules.workflow.models import State

    rows = await session.execute(
        select(WorkItem, State)
        .join(State, State.id == WorkItem.state_id, isouter=True)
        .where(WorkItem.reporter_id == actor.id)
        .where(WorkItem.archived_at.is_(None))
        .order_by(WorkItem.created_at.desc())
        .limit(limit)
    )
    pairs = list(rows.all())
    if not pairs:
        return []
    project_ids = {item.project_id for item, _ in pairs}
    projects = {
        p.id: p for p in await projects_service.list_projects(session) if p.id in project_ids
    }
    keys = await projects_service.project_keys(session, list(project_ids))
    out: list[PortalRequestRead] = []
    for item, state in pairs:
        project = projects.get(item.project_id)
        if project is None:  # a project removed under them — not their problem
            continue
        out.append(
            PortalRequestRead(
                key=f"{keys[project.id]}-{item.number}",
                title=item.title,
                state=state.name if state else "",
                state_category=state.category if state else "",
                project=PortalProjectRef(id=project.id, key=project.key, name=project.name),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )
    return out


async def submit_portal_form(
    session: AsyncSession, form_id: uuid.UUID, data: FormSubmit, actor: User
) -> PublicSubmitResult:
    """Create the item as the SYSTEM actor with the visitor as reporter — the
    sharee may hold no item.create anywhere; the share is the grant. Form
    required-overrides + registry validation apply (422), like the public path."""
    # Deferred: automations loads after forms in RADD_MODULES (public.py idiom).
    from radd.modules.automations.types import SYSTEM_ACTOR_ID

    form = await _eligible_form(session, form_id, actor)
    system = await auth.get_user(session, SYSTEM_ACTOR_ID)
    item = await service.submit_form(session, form.id, data, system, reporter_id=actor.id)
    return PublicSubmitResult(key=item.key, title=item.title)
